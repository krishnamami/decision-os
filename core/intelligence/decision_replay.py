"""CI-B — Historical decision replay (READ-ONLY).

"What would this loan have decided under a different rule version?"

Replays a recorded underwriting decision against any tenant_rules version WITHOUT
re-running the 14 personas and WITHOUT writing decision_outputs / persona_bundles:

  1. Read the recorded underwriting outcome + its rule_version_id (decision_outputs).
  2. Read the FROZEN upstream persona outcomes (persona_bundles.upstream_snapshot)
     and the numeric gate values (entity_states: mid_credit_score / dti_back / ltv).
  3. Re-resolve credit/dti/ltv thresholds at BOTH the original and the target version
     via the EXISTING ThresholdResolver(rule_version_id) — already version-parametric.
  4. Re-evaluate ONLY those three gates at the target version, swap the affected
     personas into the frozen upstream set, and re-reduce to the underwriting
     outcome (the real boundary: any block -> block; else escalate; else recommend).

This reuses CI-A's shadow-safe reduction (core/intelligence/change_impact_simulator):
a persona only flips when its gate genuinely crosses the threshold between versions,
and a flip is only "real" after re-reducing the FULL upstream set — so a loan blocked
by product_eligibility stays blocked even if its credit gate clears (no false flips).

RULE 11: data_source + missing_inputs + honest_caveat on every result. A NULL field
(e.g. SC03 dti_back) is reported in missing_inputs, never assumed.

SCOPE (honest): credit/dti/ltv threshold gates only; fraud/product/income outcomes
are held at their frozen values (their rules are not version-resolved here). Full
14-persona cascade re-run is a future slice. Read-only — nothing is written.
"""
from __future__ import annotations

from typing import Optional

from core.intelligence.change_impact_simulator import (
    ChangeImpactSimulator,
    _normalize_upstream,
    _reduce_outcome,
    _j,
)

# persona/decision -> (dotted threshold field, default, gate direction, entity field)
REPLAY_GATES: dict[str, tuple[str, float, str, str]] = {
    "credit_assessment": ("credit.min_score", 620, "gte", "mid_credit_score"),
    "dti_calculation":   ("dti.back_max",     43,  "lte", "dti_back"),
    "ltv_assessment":    ("ltv.max",          97,  "lte", "ltv"),
}

_SIM = ChangeImpactSimulator()  # stateless gate + persona-flip primitives


async def _resolve_at(resolver, version) -> dict:
    """Resolve the three replay thresholds at one rule version."""
    out: dict = {}
    for persona, (field, default, _dir, _ef) in REPLAY_GATES.items():
        res = await resolver.resolve(field, default, rule_version_id=version)
        out[field] = res.value
    return out


async def replay_decision(
    conn,
    application_id: str,
    tenant_id: str,
    target_rule_version_id: Optional[str] = None,
) -> dict:
    """Replay one application's underwriting decision against a target rule version."""
    from core.policy_engine.threshold_resolver import ThresholdResolver

    original = await conn.fetchrow(
        """SELECT DISTINCT ON (application_id)
               application_id, outcome, rule_version_id, created_at
           FROM decision_outputs
           WHERE application_id=$1 AND tenant_id=$2 AND decision_id='underwriting_decision'
           ORDER BY application_id, version DESC NULLS LAST, created_at DESC""",
        application_id, tenant_id)
    if not original:
        return {
            "success": False,
            "error": "No underwriting_decision found for this application",
            "data_source": "decision_outputs",
            "missing_inputs": ["underwriting_decision output not found"],
        }

    bundle = await conn.fetchrow(
        """SELECT upstream_snapshot FROM persona_bundles
           WHERE application_id=$1 AND tenant_id=$2
             AND persona_id='underwriting_decision' AND is_current=true
           ORDER BY version DESC LIMIT 1""",
        application_id, tenant_id)
    if not bundle:
        return {
            "success": False,
            "error": "No frozen persona_bundle found — cannot replay",
            "data_source": "persona_bundles",
            "missing_inputs": ["persona_bundles.upstream_snapshot not found"],
        }

    entity = await conn.fetchrow(
        """SELECT mid_credit_score, dti_back, ltv, loan_amount
           FROM entity_states WHERE application_id=$1 AND tenant_id=$2""",
        application_id, tenant_id)
    entity = dict(entity) if entity else {}

    original_version = str(original["rule_version_id"]) if original["rule_version_id"] else None
    target_version = str(target_rule_version_id) if target_rule_version_id else original_version
    original_outcome = original["outcome"]

    upstream = _normalize_upstream(bundle["upstream_snapshot"])
    # fidelity check — the frozen upstream must reduce to the recorded outcome
    replay_fidelity_ok = bool(upstream) and _reduce_outcome(upstream) == original_outcome

    resolver = ThresholdResolver(conn, tenant_id)
    original_thresholds = await _resolve_at(resolver, original_version)
    target_thresholds = await _resolve_at(resolver, target_version)

    sim_upstream = dict(upstream)
    gate_changes: list[dict] = []
    missing: list[str] = []
    loan_profile: dict = {}

    for persona, (field, default, direction, ef) in REPLAY_GATES.items():
        value = entity.get(ef)
        loan_profile[ef] = value
        frozen = upstream.get(persona)
        if value is None:
            missing.append(f"{ef} is NULL — gate for {persona} not evaluated (RULE 11)")
            continue
        value = float(value)
        orig_t = float(original_thresholds.get(field, default))
        targ_t = float(target_thresholds.get(field, default))
        passes_orig = _SIM._evaluate_gate(value, orig_t, direction)
        passes_targ = _SIM._evaluate_gate(value, targ_t, direction)
        sim_persona = _SIM._simulate_persona_outcome(frozen, passes_orig, passes_targ)
        if frozen is not None:
            sim_upstream[persona] = sim_persona
        if sim_persona != frozen:
            gate_changes.append({
                "persona": persona, "field": field, "value": value,
                "original_threshold": orig_t, "target_threshold": targ_t,
                "frozen_outcome": frozen, "replayed_outcome": sim_persona,
            })

    simulated_outcome = _reduce_outcome(sim_upstream) if sim_upstream else original_outcome
    outcome_changed = simulated_outcome != original_outcome

    threshold_diffs = []
    for field in sorted(set(original_thresholds) | set(target_thresholds)):
        ov, tv = original_thresholds.get(field), target_thresholds.get(field)
        if str(ov) != str(tv):
            try:
                stricter = float(tv) > float(ov) if field != "credit.min_score" else float(tv) > float(ov)
            except (TypeError, ValueError):
                stricter = None
            # credit floor: higher = stricter; dti/ltv ceiling: lower = stricter
            direction = None
            try:
                if field == "credit.min_score":
                    direction = "stricter" if float(tv) > float(ov) else "looser"
                else:
                    direction = "stricter" if float(tv) < float(ov) else "looser"
            except (TypeError, ValueError):
                direction = "changed"
            threshold_diffs.append({
                "rule": field, "original_value": ov, "target_value": tv,
                "direction": direction})

    verdict = (
        f"Under the target version this loan would be {simulated_outcome.upper()} "
        f"(was {original_outcome.upper()}). "
        f"{len(gate_changes)} gate(s) changed across {len(threshold_diffs)} threshold delta(s)."
    ) if outcome_changed else (
        f"Outcome unchanged ({original_outcome.upper()}). "
        + (f"{len(gate_changes)} gate(s) changed but the loan stays blocked by other "
           f"personas ({', '.join(p for p, o in upstream.items() if o in ('block', 'deny') and p not in REPLAY_GATES) or 'none'})."
           if gate_changes else "No credit/dti/ltv gate crossed a threshold between versions.")
    )

    return {
        "success": True,
        "application_id": application_id,
        "tenant_id": tenant_id,
        "replay_type": "cross_version",
        "replay_fidelity_ok": replay_fidelity_ok,
        "original": {
            "rule_version_id": original_version,
            "outcome": original_outcome,
            "decision_date": original["created_at"].isoformat() if original["created_at"] else None,
            "thresholds": original_thresholds,
        },
        "replayed": {
            "rule_version_id": target_version,
            "simulated_outcome": simulated_outcome,
            "gate_changes": gate_changes,
            "thresholds": target_thresholds,
        },
        "diff": {
            "outcome_changed": outcome_changed,
            "original_outcome": original_outcome,
            "replayed_outcome": simulated_outcome,
            "threshold_changes": threshold_diffs,
            "gate_changes": gate_changes,
            "verdict": verdict,
        },
        "loan_profile": loan_profile,
        "loan_amount": float(entity.get("loan_amount") or 0),
        "data_source": "decision_outputs + persona_bundles.upstream_snapshot (frozen "
                       "outcomes) + entity_states (gate values) + ThresholdResolver(version)",
        "missing_inputs": missing,
        "honest_caveat": (
            "Replays credit/dti/ltv threshold gates against the target rule version and "
            "re-reduces the FROZEN upstream outcomes (CI-A shadow-safe method — a gate that "
            "clears does not unblock a loan blocked by another persona). fraud/product/income "
            "outcomes are held at their frozen values; full 14-persona cascade re-run is a "
            "future slice. The threshold gate approximates each persona's full logic."),
    }


async def replay_all_decisions(
    conn,
    tenant_id: str,
    target_rule_version_id: str,
) -> dict:
    """Replay every application in the tenant against a target rule version."""
    apps = await conn.fetch(
        """SELECT DISTINCT application_id FROM decision_outputs
           WHERE tenant_id=$1 AND decision_id='underwriting_decision'
           ORDER BY application_id""",
        tenant_id)

    results, changed, skipped = [], [], []
    for row in apps:
        r = await replay_decision(conn, row["application_id"], tenant_id, target_rule_version_id)
        if not r.get("success"):
            skipped.append(row["application_id"])
            continue
        results.append(r)
        if r["diff"]["outcome_changed"]:
            changed.append({
                "application_id": r["application_id"],
                "original_outcome": r["diff"]["original_outcome"],
                "replayed_outcome": r["diff"]["replayed_outcome"],
                "loan_amount": r["loan_amount"],
                "gate_changes": r["diff"]["gate_changes"],
            })

    dollars_changed = sum(c["loan_amount"] for c in changed)
    return {
        "tenant_id": tenant_id,
        "target_version": target_rule_version_id,
        "total_replayed": len(results),
        "outcomes_changed": len(changed),
        "dollars_changed": dollars_changed,
        "fidelity_failures": sum(1 for r in results if not r["replay_fidelity_ok"]),
        "changed_decisions": changed,
        "skipped_applications": skipped,
        "data_source": "decision_outputs + persona_bundles + entity_states + "
                       "ThresholdResolver (read-only, no writes)",
        "missing_inputs": skipped,
        "honest_caveat": (
            "Cross-version replay of credit/dti/ltv gates; outcomes changed counts only "
            "loans whose underwriting outcome flips after re-reducing the full upstream set."),
    }

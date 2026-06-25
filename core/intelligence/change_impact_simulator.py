"""CI-A — Change Impact Simulator (READ-ONLY).

"If we moved this overlay rule, what would happen to the pipeline?"

Approach B (delta short-circuit + binding-constraint cross-check), NOT a full
14-persona re-run (that is CI-B):

  1. Each simulatable overlay rule maps to ONE entity_states field + ONE upstream
     persona + a gate direction (e.g. credit_floor -> mid_credit_score /
     credit_assessment / "score must be >= floor").
  2. For every application, re-evaluate ONLY that gate against the new hypothetical
     threshold, and re-derive the persona's outcome — but ONLY if the field was the
     plausible cause (the gate actually flips fail<->pass). A persona that blocked
     for a NON-threshold reason (bankruptcy, thin file) is left untouched.
  3. Re-reduce the recorded upstream persona outcomes (with that one persona's
     outcome swapped) to the simulated underwriting outcome. This reproduces the
     real boundary (any block -> block; else any escalate -> escalate; else
     recommend) — verified to reproduce all 16 recorded meridian outcomes.

CRITICAL CORRECTNESS — an application only "flips" if the simulated rule is its
SOLE binding constraint. SC01 (score 720, credit=allow) is blocked by dti +
fraud + product_eligibility; lowering the credit floor changes nothing. Because
we re-reduce the FULL upstream set, multi-constraint apps are excluded
automatically: swapping credit->recommend still leaves dti=block -> still block.

NOTE (spec deviation, documented): the underwriting_decision `output_payload.signals`
array is empty in the live data, so the binding constraint is read from the
authoritative `decision_outputs.upstream_decisions` column (the per-persona
outcome map), NOT from signals. That column re-reduces to the recorded outcome
16/16; `signals` would have made every app look sole-binding (the exact false-flip
bug this guard exists to prevent).

RULE 11: every result carries `data_source` + `missing_inputs`; a NULL field is
reported as missing, never assumed. NO catalogue writes. NO decision writes. The
hypothetical thresholds are always supplied by the caller — nothing is hardcoded.
"""
from __future__ import annotations

import json
from typing import Any, Optional

# rule_name -> (entity_states field, upstream persona/decision_id, gate direction).
# direction is the comparison the PASS requires:
#   "gte" -> field must be >= threshold (a floor, e.g. credit score)
#   "lte" -> field must be <= threshold (a ceiling, e.g. dti / ltv max)
SIMULATABLE_FIELDS: dict[str, tuple[str, str, str]] = {
    "credit_floor":     ("mid_credit_score", "credit_assessment", "gte"),
    "dti_back_max":     ("dti_back",          "dti_calculation",   "lte"),
    "ltv_max_purchase": ("ltv",               "ltv_assessment",    "lte"),
}

# Upstream persona outcomes, worst-first. The underwriting boundary is
# "any block -> block; else any escalate -> escalate; else recommend".
_BLOCKING = ("block", "deny")
_DECLINED = ("block", "deny")  # the "declined" terminal state for unblock framing


def _j(v: Any) -> Any:
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return {}
    return v if v is not None else {}


def _normalize_upstream(raw: Any) -> dict[str, str]:
    """upstream_decisions may be {persona: 'block'} or {persona: {'outcome': 'block'}}."""
    d = _j(raw)
    if not isinstance(d, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in d.items():
        if isinstance(v, dict):
            o = v.get("outcome")
        else:
            o = v
        if isinstance(o, str):
            out[k] = o
    return out


def _reduce_outcome(upstream: dict[str, str]) -> str:
    """Reduce per-persona outcomes to the underwriting outcome (the real boundary)."""
    vals = set(upstream.values())
    if vals & set(_BLOCKING):
        return "block"
    if "escalate" in vals:
        return "escalate"
    return "recommend"


class ChangeImpactSimulator:
    """Read-only. Simulation uses caller-supplied hypothetical values only."""

    def __init__(self) -> None:
        pass  # no rules needed — thresholds are passed in per simulate() call

    # ── pure gate + flip primitives (unit-tested directly) ──────────────────
    def _evaluate_gate(self, field_value: float, threshold: float, direction: str) -> bool:
        if direction == "gte":
            return field_value >= threshold
        if direction == "lte":
            return field_value <= threshold
        raise ValueError(f"unknown direction: {direction!r}")

    def _simulate_persona_outcome(
        self,
        current_persona_outcome: Optional[str],
        passes_current: bool,
        passes_hypothetical: bool,
    ) -> Optional[str]:
        """The controlled persona's outcome under the hypothetical threshold.

        Only flips when the FIELD GATE itself flips — so a block that was caused by
        something other than this threshold (field already passed) is left as-is,
        and a clean pass is not gratuitously blocked. Returns the (possibly
        unchanged) persona outcome.
        """
        if (not passes_current) and passes_hypothetical:
            # loosening: the field was failing, now passes -> clears IF it was blocking
            if current_persona_outcome in ("block", "deny", "escalate"):
                return "recommend"
        elif passes_current and (not passes_hypothetical):
            # tightening: the field was passing, now fails -> newly blocks a clean persona
            if current_persona_outcome in ("recommend", "allow", None):
                return "block"
        return current_persona_outcome

    def _classify(self, current_outcome: str, simulated_outcome: str) -> str:
        if simulated_outcome == current_outcome:
            return "no_change"
        was_declined = current_outcome in _DECLINED
        now_declined = simulated_outcome in _DECLINED
        if was_declined and simulated_outcome == "recommend":
            return "block_to_recommend"      # true unblock (clean approve)
        if was_declined and simulated_outcome == "escalate":
            return "block_to_review"          # improves to manual review (not auto-approve)
        if (not was_declined) and now_declined:
            return "to_block"                 # newly blocked
        if current_outcome == "recommend" and simulated_outcome == "escalate":
            return "recommend_to_review"      # new friction (not a block)
        if current_outcome == "escalate" and simulated_outcome == "recommend":
            return "review_to_recommend"      # cleared from manual review
        return "other_change"

    # ── main entry ──────────────────────────────────────────────────────────
    async def simulate(
        self,
        conn,
        tenant_id: str,
        rule_name: str,
        current_value: float,
        hypothetical_value: float,
    ) -> dict:
        """DATA SOURCES (read-only):
          entity_states            field values for the gate comparison
          decision_outputs         current outcome + upstream_decisions per app
        NO WRITES. NO CATALOGUE CHANGES.
        """
        if rule_name not in SIMULATABLE_FIELDS:
            return {
                "success": False,
                "error": f"Unknown rule: {rule_name}. "
                         f"Simulatable: {list(SIMULATABLE_FIELDS)}",
                "data_source": "SIMULATABLE_FIELDS map",
                "missing_inputs": [f"rule_name must be one of {list(SIMULATABLE_FIELDS)}"],
            }

        entity_field, controlled_persona, direction = SIMULATABLE_FIELDS[rule_name]
        current_value = float(current_value)
        hypothetical_value = float(hypothetical_value)

        # current decision per application (MAX version) + its upstream persona map
        decisions = await conn.fetch(
            """
            SELECT DISTINCT ON (application_id)
                application_id, outcome, upstream_decisions, version
            FROM decision_outputs
            WHERE tenant_id = $1 AND decision_id = 'underwriting_decision'
            ORDER BY application_id, version DESC NULLS LAST, created_at DESC
            """,
            tenant_id,
        )

        entity_rows = await conn.fetch(
            """
            SELECT application_id, loan_amount, mid_credit_score, dti_back, dti_front,
                   ltv, qualifying_monthly, total_liquid_assets
            FROM entity_states WHERE tenant_id = $1
            """,
            tenant_id,
        )
        entity_map = {r["application_id"]: dict(r) for r in entity_rows}

        results: list[dict] = []
        missing_data: list[dict] = []
        shadowed: list[dict] = []      # gate flipped but outcome unchanged (other blockers)
        total_pipeline = 0.0
        current_counts: dict[str, int] = {}
        simulated_counts: dict[str, int] = {}

        for d in decisions:
            app_id = d["application_id"]
            current_outcome = d["outcome"]
            entity = entity_map.get(app_id, {})
            loan_amount = float(entity.get("loan_amount") or 0)
            total_pipeline += loan_amount
            current_counts[current_outcome] = current_counts.get(current_outcome, 0) + 1

            field_value = entity.get(entity_field)
            if field_value is None:
                # RULE 11 — never assume; report and skip the simulation for this app.
                missing_data.append({
                    "application_id": app_id,
                    "current_outcome": current_outcome,
                    "simulated_outcome": "unknown",
                    "loan_amount": loan_amount,
                    "data_source": f"entity_states.{entity_field}",
                    "missing_inputs": [f"{entity_field} is NULL — cannot simulate this gate"],
                })
                # a missing app keeps its current outcome in the simulated tally
                simulated_counts[current_outcome] = simulated_counts.get(current_outcome, 0) + 1
                continue

            field_value = float(field_value)
            upstream = _normalize_upstream(d["upstream_decisions"])
            cur_persona = upstream.get(controlled_persona)

            passes_current = self._evaluate_gate(field_value, current_value, direction)
            passes_hypothetical = self._evaluate_gate(field_value, hypothetical_value, direction)

            sim_persona = self._simulate_persona_outcome(
                cur_persona, passes_current, passes_hypothetical
            )
            sim_upstream = dict(upstream)
            if cur_persona is not None:
                sim_upstream[controlled_persona] = sim_persona

            simulated_outcome = _reduce_outcome(sim_upstream) if sim_upstream else current_outcome
            simulated_counts[simulated_outcome] = simulated_counts.get(simulated_outcome, 0) + 1

            flip_type = self._classify(current_outcome, simulated_outcome)
            other_blockers = [
                p for p, o in upstream.items()
                if o in _BLOCKING and p != controlled_persona
            ]
            gate_flipped = (sim_persona != cur_persona)
            sole_binding = (cur_persona in _BLOCKING) and not other_blockers

            result = {
                "application_id": app_id,
                "current_outcome": current_outcome,
                "simulated_outcome": simulated_outcome,
                "flip_type": flip_type,
                "loan_amount": loan_amount,
                entity_field: field_value,
                "current_threshold": current_value,
                "hypothetical_threshold": hypothetical_value,
                "controlled_persona": controlled_persona,
                "controlled_persona_outcome": cur_persona,
                "gate_flipped": gate_flipped,
                "other_blocking_personas": other_blockers,
                "sole_binding_constraint": sole_binding,
                "data_source": f"entity_states.{entity_field} + "
                               f"decision_outputs.upstream_decisions",
                "missing_inputs": [],
            }
            results.append(result)

            # the honest "would-be flip that is shadowed by another blocker" case
            if gate_flipped and flip_type == "no_change" and cur_persona in _BLOCKING:
                shadowed.append(result)

        true_unblocks = [r for r in results if r["flip_type"] == "block_to_recommend"]
        moved_to_review = [r for r in results if r["flip_type"] == "block_to_review"]
        new_blocks = [r for r in results if r["flip_type"] == "to_block"]

        dollars_unblocked = sum(r["loan_amount"] for r in true_unblocks)
        dollars_moved_to_review = sum(r["loan_amount"] for r in moved_to_review)
        dollars_at_risk = sum(r["loan_amount"] for r in new_blocks)
        dollars_shadowed = sum(r["loan_amount"] for r in shadowed)

        direction_word = "loosened" if (
            (direction == "gte" and hypothetical_value < current_value)
            or (direction == "lte" and hypothetical_value > current_value)
        ) else "tightened"

        caveat = (
            f"Rule {direction_word} ({rule_name}: {current_value} -> {hypothetical_value}). "
            f"{len(true_unblocks)} application(s) flip block->recommend (sole-constraint only). "
            f"{len(shadowed)} application(s) would clear THIS gate but stay blocked by another "
            f"persona ({_summarize_blockers(shadowed)}) — correctly excluded from unblocks, "
            f"${dollars_shadowed:,.0f} NOT counted. "
            f"{len(missing_data)} application(s) skipped (NULL {entity_field}, RULE 11). "
            f"Dataset = {len(decisions)} applications; figures reflect this pipeline only."
        )

        return {
            "simulation_type": "change_impact",
            "tenant_id": tenant_id,
            "rule_name": rule_name,
            "entity_field": entity_field,
            "controlled_persona": controlled_persona,
            "current_value": current_value,
            "hypothetical_value": hypothetical_value,
            "direction": direction,
            "rule_direction": direction_word,
            "pipeline_summary": {
                "total_applications": len(decisions),
                "total_pipeline": total_pipeline,
                "current_outcomes": current_counts,
                "simulated_outcomes": simulated_counts,
            },
            "impact_summary": {
                "true_unblocks": len(true_unblocks),
                "dollars_unblocked": dollars_unblocked,
                "moved_to_review": len(moved_to_review),
                "dollars_moved_to_review": dollars_moved_to_review,
                "new_blocks": len(new_blocks),
                "dollars_at_risk": dollars_at_risk,
                "shadowed_by_other_constraints": len(shadowed),
                "dollars_shadowed": dollars_shadowed,
                "missing_data_apps": len(missing_data),
                "no_change_apps": sum(1 for r in results if r["flip_type"] == "no_change"),
            },
            "true_unblocks": true_unblocks,
            "moved_to_review": moved_to_review,
            "new_blocks": new_blocks,
            "shadowed": shadowed,
            "missing_data": missing_data,
            "honesty_caveat": caveat,
            "data_source": "entity_states + decision_outputs.upstream_decisions "
                           "(read-only, no writes)",
            "missing_inputs": [r["application_id"] for r in missing_data],
        }


def _summarize_blockers(shadowed: list[dict]) -> str:
    counts: dict[str, int] = {}
    for r in shadowed:
        for p in r.get("other_blocking_personas", []):
            counts[p] = counts.get(p, 0) + 1
    if not counts:
        return "none"
    return ", ".join(f"{p}={n}" for p, n in sorted(counts.items(), key=lambda x: -x[1]))


# ── convenience wrappers (return coroutines — await them) ───────────────────
def simulate_credit_floor_change(conn, tenant_id, current_floor, new_floor):
    return ChangeImpactSimulator().simulate(
        conn, tenant_id, "credit_floor", current_floor, new_floor)


def simulate_dti_change(conn, tenant_id, current_max, new_max):
    return ChangeImpactSimulator().simulate(
        conn, tenant_id, "dti_back_max", current_max, new_max)


def simulate_ltv_change(conn, tenant_id, current_max, new_max):
    return ChangeImpactSimulator().simulate(
        conn, tenant_id, "ltv_max_purchase", current_max, new_max)

"""PersonaRunner — cron-style executor that runs personas against
pending applications stored in EDMS.

  Wave 1 personas (no upstream)   → run first.
  Wave 2-5 personas (depend on N) → gated by upstream completion.

Per app per persona:
  1. Read context from the persona's EDMS view → EdmsSnapshot.
  2. Build a ContextBundle directly (skip ContextBuilder — the view is
     already the per-decision projection).
  3. Call ``persona._compute_offline(bundle, None)`` for deterministic
     reasoning.
  4. Write the outcome to ``decision_outputs`` + ``decision_timeline``.

Run all waves:           python -m core.cron.runner
Run one persona:         python -m core.cron.runner credit_assessment
Run one persona, limit:  python -m core.cron.runner credit_assessment 50
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from dotenv import load_dotenv

load_dotenv()


def _governed_by_for(decision_id: str, outcome: str):
    """Regulation citations governing this decision+outcome (from decisions.yaml).
    Best-effort — never blocks a write."""
    try:
        from domains.lending.governance import governed_by_for
        return governed_by_for(decision_id, outcome)
    except Exception:
        return None


def _is_policy_safe_default(policy: Any) -> bool:
    """True when the policy engine matched no boundary clause and fell back to
    its safe-default escalate (no hard block / contamination). In that case the
    persona's own proposed outcome is preferred so we never regress a decision
    whose output_payload fields predate the YAML boundary."""
    return (
        getattr(policy, "matched_clause", None) is None
        and str(getattr(getattr(policy, "outcome", None), "value", "")) == "escalate"
        and not getattr(policy, "contamination", False)
    )

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# Wave + persona registries.
#
# WAVE_CONFIG mirrors decisions.yaml's depends_on (kept inline so the
# runner has no YAML load cost on hot startup). The actual persona
# classes are resolved at runtime through LENDING_PERSONA_CLASSES so
# class-name drift in domains/lending/personas/__init__.py is caught
# by import errors, not silent miswire.
# ─────────────────────────────────────────────────────────────────────


WAVE_CONFIG: dict[str, dict[str, Any]] = {
    "credit_assessment":         {"wave": 1, "upstream": []},
    "fraud_screening":           {"wave": 1, "upstream": []},
    "compliance_check":          {"wave": 1, "upstream": []},
    "employment_reconciliation": {"wave": 1, "upstream": []},
    "asset_verification":        {"wave": 1, "upstream": []},
    "title_assessment":          {"wave": 1, "upstream": []},
    "income_verification":       {"wave": 2, "upstream": ["employment_reconciliation"]},
    "dti_calculation":           {"wave": 2, "upstream": ["income_verification"]},
    "ltv_assessment":            {"wave": 2, "upstream": ["credit_assessment"]},
    "product_eligibility":       {"wave": 3, "upstream": ["dti_calculation", "ltv_assessment"]},
    "rate_pricing":              {"wave": 3, "upstream": ["credit_assessment", "dti_calculation", "ltv_assessment"]},
    "underwriting_decision":     {"wave": 4, "upstream": [
        "income_verification", "credit_assessment", "fraud_screening",
        "dti_calculation", "ltv_assessment", "product_eligibility",
    ]},
    "approval_routing":          {"wave": 5, "upstream": ["underwriting_decision"]},
    "closing_readiness":         {"wave": 5, "upstream": ["underwriting_decision", "compliance_check"]},
}

WAVES: tuple[tuple[str, ...], ...] = (
    ("credit_assessment", "fraud_screening", "compliance_check", "employment_reconciliation", "asset_verification", "title_assessment"),
    ("income_verification", "dti_calculation", "ltv_assessment"),
    ("product_eligibility", "rate_pricing"),
    ("underwriting_decision",),
    ("approval_routing", "closing_readiness"),
)


# Default SLA + risk_level when decisions.yaml isn't loaded. Kept in
# sync with domains/lending/decisions.yaml. Fetching from YAML on every
# run isn't worth the parse — these values change rarely.
DECISION_DEFAULTS: dict[str, dict[str, Any]] = {
    "credit_assessment":         {"sla_seconds": 30,  "risk_level": "medium", "mode": "recommend"},
    "fraud_screening":           {"sla_seconds": 30,  "risk_level": "high",   "mode": "human_approval"},
    "compliance_check":          {"sla_seconds": 60,  "risk_level": "high",   "mode": "human_approval"},
    "employment_reconciliation": {"sla_seconds": 60,  "risk_level": "medium", "mode": "recommend"},
    "asset_verification":        {"sla_seconds": 30,  "risk_level": "medium", "mode": "recommend"},
    "title_assessment":          {"sla_seconds": 30,  "risk_level": "medium", "mode": "recommend"},
    "income_verification":       {"sla_seconds": 60,  "risk_level": "medium", "mode": "recommend"},
    "dti_calculation":           {"sla_seconds": 10,  "risk_level": "low",    "mode": "auto_execute"},
    "ltv_assessment":            {"sla_seconds": 10,  "risk_level": "low",    "mode": "auto_execute"},
    "product_eligibility":       {"sla_seconds": 30,  "risk_level": "medium", "mode": "recommend"},
    "rate_pricing":              {"sla_seconds": 30,  "risk_level": "medium", "mode": "recommend"},
    "underwriting_decision":     {"sla_seconds": 120, "risk_level": "high",   "mode": "human_approval"},
    "approval_routing":          {"sla_seconds": 30,  "risk_level": "low",    "mode": "auto_execute"},
    "closing_readiness":         {"sla_seconds": 60,  "risk_level": "high",   "mode": "human_approval"},
}


def _looks_like_conn_error(exc: BaseException) -> bool:
    """Heuristic — is this a transient connection-level failure worth
    a single pool reset + retry?

    We match by class (asyncpg's PostgresConnectionError, builtin
    ConnectionError / ConnectionResetError) AND by string sniffing
    against the message ("connection is closed", "ConnectionReset"
    per the spec, plus a few common variants) so we catch wrapped /
    re-raised errors that lose their original type.
    """
    if isinstance(exc, (ConnectionError, ConnectionResetError)):
        return True
    try:
        import asyncpg  # type: ignore

        if isinstance(exc, asyncpg.PostgresConnectionError):
            return True
        if isinstance(exc, asyncpg.InterfaceError):
            return True
    except ImportError:  # pragma: no cover — asyncpg always present here
        pass
    msg = str(exc).lower()
    needles = (
        "connection is closed",
        "connection was closed",
        "connection lost",
        "connectionreset",
        "connection reset",
        "server closed the connection",
        "connection has been closed",
    )
    return any(n in msg for n in needles)


class PersonaRunner:
    """Run a single persona or all waves end-to-end against EDMS."""

    def __init__(self, database_url: str):
        # Local imports to keep test imports light.
        from core.edms_store import EdmsContextStore
        from core.decision_store import DecisionStore

        self.database_url = database_url
        self.edms_store = EdmsContextStore(database_url)
        self.decision_store = DecisionStore(database_url)
        self._agents: dict[str, Any] = {}
        self._evaluator: Any = None  # lazy PolicyEvaluator (decisions.yaml)
        self._learnings_present: dict[str, bool] = {}  # tenant → has active lessons

    async def close(self) -> None:
        await self.edms_store.close()
        await self.decision_store.close()

    # ── Pool lifecycle helpers ────────────────────────────────────────

    async def _reset_pools(self) -> None:
        """Close both stores' asyncpg pools and clear the singletons so
        the next call to ``_get_pool()`` rebuilds. Used both on
        transient connection errors and pre-emptively every 500 rows
        to keep the runner clear of the RDS idle reaper."""
        for store in (self.edms_store, self.decision_store):
            pool = getattr(store, "_pool", None)
            if pool is not None:
                try:
                    await pool.close()
                except Exception:  # noqa: BLE001 — best-effort teardown
                    pass
            store._pool = None

    # ── Persona resolution ───────────────────────────────────────────

    def _get_agent(self, decision_id: str) -> Any:
        """Look up the persona via LENDING_PERSONA_CLASSES (single
        source of truth for class names)."""
        if decision_id in self._agents:
            return self._agents[decision_id]

        try:
            personas_mod = importlib.import_module("domains.lending.personas")
            classes = getattr(personas_mod, "LENDING_PERSONA_CLASSES")
        except (ImportError, AttributeError) as err:
            raise RuntimeError(
                "Could not load LENDING_PERSONA_CLASSES from "
                "domains.lending.personas"
            ) from err

        cls = classes.get(decision_id)
        if cls is None:
            raise KeyError(f"No persona class registered for {decision_id!r}")
        self._agents[decision_id] = cls()
        return self._agents[decision_id]

    # ── One persona run ──────────────────────────────────────────────

    async def run_persona(
        self,
        decision_id: str,
        batch_size: int = 9000,
        tenant_id: str = "default",
    ) -> dict[str, Any]:
        """Run ``decision_id`` for up to ``batch_size`` pending apps."""
        # Local imports so a missing ContextBundle / OfflineReasoning
        # import doesn't break the runner's module load.
        from core.context_store import ContextBundle

        config = WAVE_CONFIG[decision_id]
        wave = config["wave"]
        upstream: list[str] = list(config["upstream"])
        defaults = DECISION_DEFAULTS.get(decision_id, {})
        sla = int(defaults.get("sla_seconds", 30))
        risk_level = defaults.get("risk_level", "medium")
        mode = defaults.get("mode", "recommend")

        pending = await self.decision_store.get_pending(
            decision_id, upstream or None, tenant_id
        )
        if not pending:
            logger.info("%s: no pending applications", decision_id)
            return {"decision_id": decision_id, "processed": 0, "remaining": 0, "errors": []}

        batch = pending[:batch_size]
        logger.info(
            "%s: %d pending, processing %d", decision_id, len(pending), len(batch)
        )

        agent = self._get_agent(decision_id)
        processed = 0
        errors: list[dict[str, Any]] = []

        for app_id in batch:
            try:
                await self._process_one(
                    app_id, decision_id, wave, upstream, mode, risk_level,
                    sla, agent, tenant_id,
                )
                processed += 1
            except Exception as exc:  # noqa: BLE001 — first-try catch-all
                # Connection-level errors (RDS idle reaper, pgbouncer
                # invalidation, network blip) are usually transient.
                # Drop both pools and retry the row once before giving
                # up. Non-connection errors fall through to the error
                # log without a retry.
                if _looks_like_conn_error(exc):
                    logger.warning(
                        "%s: connection error on %s — resetting pools and "
                        "retrying once: %s",
                        decision_id, app_id, exc,
                    )
                    await self._reset_pools()
                    try:
                        await self._process_one(
                            app_id, decision_id, wave, upstream, mode,
                            risk_level, sla, agent, tenant_id,
                        )
                        processed += 1
                    except Exception as exc2:  # noqa: BLE001
                        logger.error(
                            "%s: retry failed on %s: %s",
                            decision_id, app_id, exc2,
                        )
                        errors.append(
                            {"application_id": app_id, "error": str(exc2)}
                        )
                        continue
                else:
                    logger.error(
                        "%s: error processing %s: %s",
                        decision_id, app_id, exc,
                    )
                    errors.append({"application_id": app_id, "error": str(exc)})
                    continue

            if processed % 100 == 0:
                logger.info(
                    "%s: processed %d/%d", decision_id, processed, len(batch)
                )
            # Pre-emptively cycle the pools every 500 rows so connections
            # don't grow stale across the rest of the batch — RDS likes
            # to close idle conns after ~5–10 min and the runner can sit
            # below that floor for a long time on a big persona.
            if processed and processed % 500 == 0:
                await self._reset_pools()

        remaining = max(0, len(pending) - len(batch))
        logger.info(
            "%s: done — %d processed, %d errors, %d remaining",
            decision_id, processed, len(errors), remaining,
        )
        return {
            "decision_id": decision_id,
            "processed": processed,
            "errors": errors,
            "remaining": remaining,
        }

    # ── Per-app body (extracted so the connection-retry path can call
    #    it twice without duplicating the SQL flow) ──────────────────

    async def _process_one(
        self,
        app_id: str,
        decision_id: str,
        wave: int,
        upstream: list[str],
        mode: str,
        risk_level: str,
        sla: int,
        agent: Any,
        tenant_id: str,
    ) -> None:
        from core.context_store import ContextBundle

        start = time.time()
        snapshot = await self.edms_store.snapshot(
            application_id=app_id,
            decision_id=decision_id,
            upstream_decision_ids=upstream or None,
        )

        # EV-F (RA-3B): enrich the context with evidence facts from
        # fact_nodes BEFORE any persona reads the bundle. Non-destructive
        # (adds an "evidence" object alongside the entity_states-derived
        # objects), best-effort (never breaks a decision). No persona/policy
        # logic reads these yet — that's RA-3D.
        try:
            from core.evidence.context_enricher import ContextEnricher
            pool = await self.decision_store._get_pool()
            async with pool.acquire() as conn:
                facts = await ContextEnricher(conn).evidence_facts(
                    app_id, tenant_id, decision_id=decision_id
                )
                snapshot.context["evidence"] = {app_id: facts}
                # RA-4A: resolvers are sync/DB-less, so catalogue rules they
                # need are resolved here (async, has conn) and injected via the
                # bundle. Loaded only for the decision that uses them — with a
                # one-shot retry so a transient blip doesn't drop the rules
                # (and with them the bundle's rules_snapshot). RA-4H.
                await self._inject_decision_rules(
                    conn, snapshot, app_id, decision_id, tenant_id
                )
        except Exception:  # noqa: BLE001 — enrichment must never break a decision
            pass

        bundle = ContextBundle(
            decision_id=decision_id,
            application_id=app_id,
            snapshot_id=uuid4(),
            snapshot_at=datetime.now(timezone.utc),
            objects=snapshot.context,
            upstream_outputs=snapshot.upstream_outputs,
            upstream_decision_ids=upstream,
        )

        # Upstream outcomes — needed both for the legacy write below and for
        # the policy engine's hard-rule / contamination checks.
        upstream_data = (
            await self.decision_store.get_upstream(app_id, upstream, tenant_id)
            if upstream else {}
        )

        # 0. PROMPT L — recall relevant past human-override lessons for this
        #    decision before evaluation. Best-effort and forward-looking
        #    (personas don't consume it yet); never affects outcome or raises.
        await self._recall_lessons(decision_id, tenant_id)

        # 1. Domain values. Personas compute dti/ltv/credit from the bundle;
        #    they do NOT pick thresholds from `policy` — the policy engine does
        #    that next. (Pass None here; this is value extraction only.)
        prelim = agent._compute_offline(bundle, None)

        # 2. Wire ThresholdResolver into the cron path. Resolve which
        #    tenant_rules version governs THIS loan (pinned at rate lock →
        #    pipeline-cutoff protection → current active), then let the policy
        #    engine evaluate the boundary with tenant/agency-resolved
        #    thresholds. This is what makes a Summit loan at DTI 44% block
        #    (their cap) while a demo-tenant loan recommends (agency cap 50) —
        #    decisions.yaml thresholds become dynamic per tenant, and a
        #    rate-locked loan stays scored under its pinned version.
        policy = await self._evaluate_with_resolver(
            decision_id, prelim.output_payload, upstream_data, tenant_id, app_id,
        )

        # 3. Re-run with the resolved policy in hand (no longer None) so any
        #    persona that consumes it gets it. Values are unchanged.
        reasoning = agent._compute_offline(bundle, policy)

        # 4. The policy engine has the last word on outcome
        #    (no_action_without_policy). Fall back to the persona's proposal
        #    only when the engine matched no boundary clause (its safe-default
        #    escalate) — this avoids regressing personas whose output_payload
        #    field names predate the YAML boundary.
        if policy is not None and not _is_policy_safe_default(policy):
            outcome = policy.outcome.value
        else:
            outcome = reasoning.proposed_outcome.value
        actual = time.time() - start

        decision_uuid = await self.decision_store.write_decision(
            application_id=app_id,
            decision_id=decision_id,
            wave=wave,
            outcome=outcome,
            mode=getattr(agent, "mode", mode),
            risk_level=getattr(agent, "risk_level", risk_level),
            boundary_matched=outcome,
            boundary_rule=reasoning.conclusion,
            context_snapshot=reasoning.output_payload,
            reasoning={
                "hypothesis": reasoning.hypothesis,
                "conclusion": reasoning.conclusion,
                "confidence_basis": reasoning.confidence_basis,
                "summary": reasoning.summary,
                "signals": [
                    {"name": s.name, "value": s.value}
                    for s in (reasoning.signals or [])
                ],
            },
            confidence=float(reasoning.confidence),
            upstream_decisions=upstream_data,
            sla_seconds=sla,
            actual_seconds=actual,
            tenant_id=tenant_id,
            governed_by=_governed_by_for(decision_id, outcome),
        )

        # RA-3F: freeze exactly what THIS persona saw as a persona_bundles audit
        # snapshot, then stamp decision_outputs.bundle_id. Runs AFTER the decision
        # is committed and is strictly best-effort — the memory bundle is the live
        # source of truth; the PG bundle is the audit/replay record. A failure
        # here must never fail the decision (it is already written).
        try:
            await self._write_persona_bundle(
                app_id, tenant_id, decision_id, decision_uuid, bundle,
            )
        except Exception as exc:  # noqa: BLE001 — bundle write never blocks a decision
            logger.warning(
                "%s: persona_bundle snapshot failed for %s "
                "(decision already committed): %s",
                decision_id, app_id, exc,
            )

    # ── RA-4H — catalogue rule injection (one-shot retry) ─────────────

    async def _inject_decision_rules(
        self,
        conn: Any,
        snapshot: Any,
        app_id: str,
        decision_id: str,
        tenant_id: str,
    ) -> None:
        """Resolve the catalogue rules this decision's resolver reads and attach
        them to the snapshot context. Best-effort with a ONE-SHOT retry: a
        transient blip on the first load shouldn't drop the rules (which would
        leave the persona on SAFE_DEFAULTS for that run and the bundle's
        rules_snapshot empty — the RA-3F SC03 case). Only the four decisions
        whose resolvers consume catalogue rules load anything."""
        if decision_id == "asset_verification":
            from core.assets.asset_resolver import load_asset_rules
            key, loader = "asset_rules", load_asset_rules
        elif decision_id == "credit_assessment":
            from core.credit.findings_resolver import load_credit_rules
            key, loader = "credit_rules", load_credit_rules
        elif decision_id == "product_eligibility":
            from core.collateral.property_eligibility_resolver import (
                load_collateral_rules,
            )
            key, loader = "collateral_rules", load_collateral_rules
        elif decision_id == "title_assessment":
            from core.title.lien_resolver import load_lien_rules
            key, loader = "lien_rules", load_lien_rules
        elif decision_id == "income_verification":
            from core.income.w2_income_resolver import load_income_rules
            key, loader = "income_rules", load_income_rules
        elif decision_id == "dti_calculation":
            from core.obligations.obligation_resolver import load_obligation_rules
            key, loader = "obligation_rules", load_obligation_rules
        else:
            return

        try:
            rules = await loader(conn, tenant_id)
        except Exception:  # noqa: BLE001 — one transient retry before giving up
            try:
                rules = await loader(conn, tenant_id)
            except Exception as exc:  # noqa: BLE001 — never breaks the decision
                logger.warning(
                    "rule injection failed after retry for %s/%s: %s",
                    decision_id, app_id, exc,
                )
                return
        snapshot.context[key] = {app_id: rules}

    # ── RA-3F — persona bundle audit snapshot ─────────────────────────

    async def _write_persona_bundle(
        self,
        application_id: str,
        tenant_id: str,
        decision_id: str,
        decision_uuid: Any,
        bundle: Any,
    ) -> str:
        """Freeze the ContextBundle the persona saw into persona_bundles and
        point the just-written decision_outputs row at it.

        Snapshots are taken from the REAL bundle structure (ContextBundle.objects
        is ot_id->entity_id->fields, with the runner's injected ``evidence`` and
        ``*_rules`` keys alongside; upstream_outputs is the prior-decision blobs):
          evidence_snapshot ← objects['evidence']
          rules_snapshot    ← objects['{asset,credit,collateral,lien}_rules']
          entity_snapshot   ← the remaining (entity_states / view) objects
          upstream_snapshot ← bundle.upstream_outputs

        Same conn/transaction for the bundle insert + the FK back-write, keyed by
        the exact decision_outputs.id so only the current version is stamped
        (decision_outputs is append-only/versioned)."""
        import json

        objects = dict(getattr(bundle, "objects", None) or {})
        evidence_snap = objects.pop("evidence", {})
        rules_snap = {
            k: objects.pop(k)
            for k in ("asset_rules", "credit_rules", "collateral_rules",
                      "lien_rules", "income_rules", "obligation_rules")
            if k in objects
        }
        entity_snap = objects  # whatever remains = entity_states / view projection
        upstream_snap = getattr(bundle, "upstream_outputs", None) or {}

        pool = await self.decision_store._get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                cur = await conn.fetchval(
                    """
                    SELECT COALESCE(MAX(version), 0)
                    FROM persona_bundles
                    WHERE application_id = $1 AND persona_id = $2 AND tenant_id = $3
                    """,
                    application_id, decision_id, tenant_id,
                )
                next_version = (cur or 0) + 1

                await conn.execute(
                    """
                    UPDATE persona_bundles SET is_current = false
                    WHERE application_id = $1 AND persona_id = $2 AND tenant_id = $3
                      AND is_current = true
                    """,
                    application_id, decision_id, tenant_id,
                )

                bundle_id = await conn.fetchval(
                    """
                    INSERT INTO persona_bundles (
                        application_id, tenant_id, persona_id,
                        version, is_current,
                        entity_snapshot, evidence_snapshot,
                        rules_snapshot, upstream_snapshot
                    ) VALUES ($1,$2,$3,$4,true,$5,$6,$7,$8)
                    RETURNING id
                    """,
                    application_id, tenant_id, decision_id, next_version,
                    json.dumps(entity_snap, default=str),
                    json.dumps(evidence_snap, default=str),
                    json.dumps(rules_snap, default=str),
                    json.dumps(upstream_snap, default=str),
                )

                # Stamp ONLY the row just written (versioned table — never the
                # historical versions).
                await conn.execute(
                    "UPDATE decision_outputs SET bundle_id = $1 WHERE id = $2",
                    bundle_id, decision_uuid,
                )

        return str(bundle_id)

    # ── Policy engine wiring (ThresholdResolver + PolicyEvaluator) ────

    def _get_evaluator(self) -> Any:
        """Lazily load the decisions.yaml-backed PolicyEvaluator once."""
        if self._evaluator is None:
            from pathlib import Path
            from core.policy_engine.evaluator import PolicyEvaluator
            path = (
                Path(__file__).resolve().parents[2]
                / "domains" / "lending" / "decisions.yaml"
            )
            self._evaluator = PolicyEvaluator.from_path(path)
        return self._evaluator

    async def _resolve_rule_version(
        self, conn: Any, tenant_id: str, application_id: str
    ) -> Any:
        """Which tenant_rules version governs this loan, by priority:
          1. pinned_rule_version (set at rate lock — the rain check)
          2. pipeline-cutoff protection (submitted before a newer version's
             cutoff → grandfathered under the prior version)
          3. current active version

        Mirrors api/accord/pipeline.resolve_applicable_rules but returns just
        the version id and stays in core/ so the cron path takes no api/
        (FastAPI) import. Returns the rule_version_id (uuid) or None."""
        es = await conn.fetchrow(
            "SELECT pinned_rule_version, application_date FROM entity_states "
            "WHERE application_id=$1 AND tenant_id=$2",
            application_id, tenant_id,
        )
        # 1. Explicit pin at rate lock.
        if es and es["pinned_rule_version"]:
            return es["pinned_rule_version"]
        # 2. Pipeline-cutoff protection.
        app_date = es["application_date"] if es else None
        if app_date:
            prot = await conn.fetchrow(
                """
                SELECT prev.rule_version_id
                FROM tenant_rules curr
                JOIN tenant_rules prev ON prev.tenant_id = curr.tenant_id
                  AND prev.version = curr.version - 1
                WHERE curr.tenant_id = $1 AND curr.status = 'active'
                  AND curr.pipeline_cutoff_date IS NOT NULL
                  AND curr.pipeline_cutoff_date > $2
                ORDER BY curr.version DESC LIMIT 1
                """,
                tenant_id, app_date,
            )
            if prot:
                return prot["rule_version_id"]
        # 3. Current active version.
        cur = await conn.fetchrow(
            "SELECT rule_version_id FROM tenant_rules "
            "WHERE tenant_id=$1 AND status='active' ORDER BY version DESC LIMIT 1",
            tenant_id,
        )
        return cur["rule_version_id"] if cur else None

    async def _evaluate_with_resolver(
        self,
        decision_id: str,
        context: dict[str, Any],
        upstream_data: dict[str, Any],
        tenant_id: str,
        application_id: str,
    ) -> Any:
        """Evaluate the decision boundary with a tenant/agency ThresholdResolver
        wired to the loan's applicable rule version. Returns a PolicyDecision,
        or None if evaluation fails (caller falls back to the persona)."""
        from core.policy_engine.evaluator import PolicyOutcome, UpstreamSummary
        from core.policy_engine.threshold_resolver import ThresholdResolver

        try:
            pool = await self.decision_store._get_pool()
            async with pool.acquire() as conn:
                rule_version_id = await self._resolve_rule_version(
                    conn, tenant_id, application_id
                )
                resolver = ThresholdResolver(
                    conn, tenant_id=tenant_id, rule_version_id=rule_version_id
                )
                summaries: list[Any] = []
                for did, val in (upstream_data or {}).items():
                    try:
                        summaries.append(
                            UpstreamSummary(
                                decision_id=did,
                                outcome=PolicyOutcome(val.get("outcome")),
                                confidence=float(val.get("confidence") or 1.0),
                            )
                        )
                    except Exception:  # noqa: BLE001 — skip unmappable upstream
                        continue
                return await self._get_evaluator().evaluate(
                    decision_id, context, upstream=summaries, resolver=resolver
                )
        except Exception as exc:  # noqa: BLE001 — never let policy eval crash cron
            logger.warning(
                "%s: policy evaluation failed for %s — using persona outcome: %s",
                decision_id, application_id, exc,
            )
            return None

    # ── PROMPT L — recall past override lessons before evaluation ──────

    async def _recall_lessons(self, decision_id: str, tenant_id: str) -> str:
        """Pull relevant past human-override lessons for this decision (PROMPT L).
        Gated by a per-tenant 'has any lessons' check so tenants without overrides
        cost no extra query. Best-effort: never raises, never affects outcome."""
        try:
            if self._learnings_present.get(tenant_id) is False:
                return ""
            pool = await self.decision_store._get_pool()
            if tenant_id not in self._learnings_present:
                async with pool.acquire() as conn:
                    has = await conn.fetchval(
                        "SELECT 1 FROM agent_learnings "
                        "WHERE tenant_id=$1 AND expires_at > NOW() LIMIT 1",
                        tenant_id)
                self._learnings_present[tenant_id] = bool(has)
                if not has:
                    return ""
            from core.trace.postgres_learning_store import PostgresLearningStore
            from core.trace.reflection import ReflectionService
            store = PostgresLearningStore(pool, tenant_id)
            lessons = await ReflectionService(store).recall(
                agent_id=decision_id, decision_id=decision_id, limit=3)
            if not lessons:
                return ""
            return "\n".join(f"{i + 1}. {l.lesson}" for i, l in enumerate(lessons))
        except Exception as exc:  # noqa: BLE001
            logger.debug("lesson recall failed for %s: %s", decision_id, exc)
            return ""

    # ── All waves ────────────────────────────────────────────────────

    async def run_all_waves(
        self,
        batch_size: int = 9000,
        tenant_id: str = "default",
    ) -> dict[str, dict[str, Any]]:
        results: dict[str, dict[str, Any]] = {}
        for wave_num, decisions in enumerate(WAVES, 1):
            logger.info("=== WAVE %d ===", wave_num)
            for decision_id in decisions:
                results[decision_id] = await self.run_persona(
                    decision_id, batch_size, tenant_id
                )
        # PROMPT L — after a full sweep, refresh policy proposals from any new
        # override patterns. Best-effort; never fails the run.
        await run_pattern_detection(await self.decision_store._get_pool(), tenant_id)
        return results


async def run_pattern_detection(pool: Any, tenant_id: str) -> None:
    """Detect recurring override patterns and raise policy proposals (PROMPT L)."""
    try:
        from core.cron.pattern_detector import detect_patterns
        async with pool.acquire() as conn:
            n = await detect_patterns(conn, tenant_id)
            if n > 0:
                logger.info("Pattern detector: %d proposals created for %s", n, tenant_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Pattern detector error for %s: %s", tenant_id, exc)


# ─────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────


async def main() -> None:
    import sys

    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL environment variable not set")

    runner = PersonaRunner(database_url)
    try:
        if len(sys.argv) > 1:
            decision_id = sys.argv[1]
            batch_size = int(sys.argv[2]) if len(sys.argv) > 2 else 9000
            result = await runner.run_persona(decision_id, batch_size=batch_size)
            print(result)
        else:
            results = await runner.run_all_waves()
            for decision_id, result in results.items():
                print(
                    f"{decision_id}: "
                    f"{result['processed']} processed, "
                    f"{len(result.get('errors', []))} errors, "
                    f"{result.get('remaining', 0)} remaining"
                )
    finally:
        await runner.close()


if __name__ == "__main__":
    asyncio.run(main())

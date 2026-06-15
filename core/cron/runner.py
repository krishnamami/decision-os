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
    ("credit_assessment", "fraud_screening", "compliance_check", "employment_reconciliation"),
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
        bundle = ContextBundle(
            decision_id=decision_id,
            application_id=app_id,
            snapshot_id=uuid4(),
            snapshot_at=datetime.now(timezone.utc),
            objects=snapshot.context,
            upstream_outputs=snapshot.upstream_outputs,
            upstream_decision_ids=upstream,
        )
        reasoning = agent._compute_offline(bundle, None)
        outcome = reasoning.proposed_outcome.value
        actual = time.time() - start

        upstream_data = (
            await self.decision_store.get_upstream(app_id, upstream, tenant_id)
            if upstream else {}
        )
        await self.decision_store.write_decision(
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
        return results


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

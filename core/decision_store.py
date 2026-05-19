"""DecisionStore — append-only writes to EDMS's decision_outputs +
decision_timeline tables, plus the pending-applications / upstream
reads the cron runner needs to walk the DAG.

Versioning: ``decision_outputs`` is append-only. Each write bumps
``version`` for the same (application_id, decision_id, tenant_id). All
``get_upstream`` / pipeline reads select MAX(version).

Timeline: every write also inserts one ``decision_timeline`` row so the
state-transition history of an application is reconstructable from
``transition_at``-ordered rows."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4


# All 12 lending decisions, in the canonical order used for
# pipeline_position display in decision_timeline.
ALL_DECISIONS: tuple[str, ...] = (
    "credit_assessment",
    "fraud_screening",
    "compliance_check",
    "employment_reconciliation",
    "income_verification",
    "dti_calculation",
    "ltv_assessment",
    "product_eligibility",
    "rate_pricing",
    "underwriting_decision",
    "approval_routing",
    "closing_readiness",
)
_TOTAL_DECISIONS = len(ALL_DECISIONS)


class DecisionStore:
    """Append-only decision writer + reader, EDMS PG-backed."""

    def __init__(self, database_url: str):
        self._database_url = database_url
        self._pool: Optional[Any] = None

    async def _get_pool(self) -> Any:
        if self._pool is None:
            import asyncpg  # type: ignore
            # Tuned for long-running batch processing — see EdmsContextStore
            # for the rationale on each param. Both stores share the same
            # tuning so a runner walking thousands of rows can't get a
            # mix-and-match pool from one side and a stale pool from the
            # other.
            self._pool = await asyncpg.create_pool(
                self._database_url,
                min_size=2,
                max_size=10,
                command_timeout=60,
                max_inactive_connection_lifetime=300,
                statement_cache_size=0,
            )
        return self._pool

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    # ── Writes ───────────────────────────────────────────────────────

    async def write_decision(
        self,
        *,
        application_id: str,
        decision_id: str,
        wave: int,
        outcome: str,
        mode: str,
        risk_level: str,
        boundary_matched: Optional[str],
        boundary_rule: Optional[str],
        context_snapshot: Optional[dict[str, Any]],
        reasoning: Optional[dict[str, Any]],
        confidence: float,
        upstream_decisions: Optional[dict[str, Any]],
        sla_seconds: int,
        actual_seconds: float,
        tenant_id: str = "default",
    ) -> UUID:
        """Insert decision_outputs + decision_timeline rows atomically."""
        pool = await self._get_pool()
        now = datetime.now(timezone.utc)
        decision_uuid = uuid4()

        async with pool.acquire() as conn:
            async with conn.transaction():
                current_version = await conn.fetchval(
                    """
                    SELECT COALESCE(MAX(version), 0)
                    FROM decision_outputs
                    WHERE application_id = $1
                      AND decision_id = $2
                      AND tenant_id = $3
                    """,
                    application_id,
                    decision_id,
                    tenant_id,
                )
                new_version = (current_version or 0) + 1

                await conn.execute(
                    """
                    INSERT INTO decision_outputs (
                        id, application_id, decision_id, wave, outcome, mode,
                        risk_level, boundary_matched, boundary_rule,
                        context_snapshot, reasoning, confidence,
                        upstream_decisions, sla_seconds, actual_seconds,
                        version, tenant_id, decided_at, created_at
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12,
                            $13, $14, $15, $16, $17, $18, $19)
                    """,
                    decision_uuid,
                    application_id,
                    decision_id,
                    wave,
                    outcome,
                    mode,
                    risk_level,
                    boundary_matched,
                    boundary_rule,
                    json.dumps(context_snapshot, default=str) if context_snapshot is not None else None,
                    json.dumps(reasoning, default=str) if reasoning is not None else None,
                    confidence,
                    json.dumps(upstream_decisions, default=str) if upstream_decisions else None,
                    sla_seconds,
                    actual_seconds,
                    new_version,
                    tenant_id,
                    now,
                    now,
                )

                prev = await conn.fetchrow(
                    """
                    SELECT to_state, transition_at
                    FROM decision_timeline
                    WHERE application_id = $1 AND decision_id = $2 AND tenant_id = $3
                    ORDER BY transition_at DESC
                    LIMIT 1
                    """,
                    application_id,
                    decision_id,
                    tenant_id,
                )
                from_state = prev["to_state"] if prev else "pending"
                time_in_prev = (
                    (now - prev["transition_at"]).total_seconds() if prev else 0.0
                )

                first_entry = await conn.fetchval(
                    """
                    SELECT MIN(transition_at) FROM decision_timeline
                    WHERE application_id = $1 AND tenant_id = $2
                    """,
                    application_id,
                    tenant_id,
                )
                cumulative = (now - first_entry).total_seconds() if first_entry else 0.0

                completed_rows = await conn.fetch(
                    """
                    SELECT DISTINCT decision_id FROM decision_outputs
                    WHERE application_id = $1 AND tenant_id = $2
                    """,
                    application_id,
                    tenant_id,
                )
                completed_ids = {r["decision_id"] for r in completed_rows}
                pipeline_position = f"{len(completed_ids)} of {_TOTAL_DECISIONS}"
                waiting_on = [
                    d for d in ALL_DECISIONS
                    if d != decision_id and d not in completed_ids
                ]

                await conn.execute(
                    """
                    INSERT INTO decision_timeline (
                        application_id, decision_id, wave, from_state, to_state,
                        trigger, transition_at, time_in_prev_state_seconds,
                        cumulative_elapsed_seconds, waiting_on, pipeline_position,
                        tenant_id
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                    """,
                    application_id,
                    decision_id,
                    wave,
                    from_state,
                    outcome,
                    "cron_eval",
                    now,
                    time_in_prev,
                    cumulative,
                    json.dumps(waiting_on),
                    pipeline_position,
                    tenant_id,
                )

        return decision_uuid

    # ── Reads ────────────────────────────────────────────────────────

    async def get_upstream(
        self,
        application_id: str,
        upstream_decision_ids: Optional[list[str]],
        tenant_id: str = "default",
    ) -> dict[str, dict[str, Any]]:
        """Latest-version upstream outcomes for dependency checks."""
        if not upstream_decision_ids:
            return {}
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT decision_id, outcome, confidence, decided_at,
                       context_snapshot, reasoning
                FROM decision_outputs
                WHERE application_id = $1
                  AND decision_id = ANY($2)
                  AND tenant_id = $3
                  AND version = (
                    SELECT MAX(version) FROM decision_outputs d2
                    WHERE d2.application_id = decision_outputs.application_id
                      AND d2.decision_id = decision_outputs.decision_id
                      AND d2.tenant_id = decision_outputs.tenant_id
                  )
                """,
                application_id,
                list(upstream_decision_ids),
                tenant_id,
            )
        return {
            r["decision_id"]: {
                "outcome": r["outcome"],
                "confidence": r["confidence"],
                "decided_at": str(r["decided_at"]) if r["decided_at"] else None,
            }
            for r in rows
        }

    async def get_pending(
        self,
        decision_id: str,
        upstream_decision_ids: Optional[list[str]] = None,
        tenant_id: str = "default",
    ) -> list[str]:
        """Application ids that need this decision evaluated.

        Wave 1: applications in ``entity_states`` with no decision output
                yet for this decision_id.
        Dependent: same, gated on every listed upstream being FINALIZED.

        Finalization predicate (the human-approval gate):
          - mode = 'auto_execute' — machine decided, no human needed
          - mode IN ('human_approval', 'recommend')
              AND human_action IS NOT NULL — a reviewer has acted

        Without this gate the runner walks downstream as soon as upstream
        rows exist, even if those rows are recommend/human_approval
        proposals nobody has reviewed yet — and the pipeline becomes a
        black box that hides whether decisions had real oversight."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            if not upstream_decision_ids:
                rows = await conn.fetch(
                    """
                    SELECT DISTINCT es.application_id
                    FROM entity_states es
                    WHERE es.tenant_id = $1
                      AND es.application_id NOT IN (
                        SELECT application_id FROM decision_outputs
                        WHERE decision_id = $2 AND tenant_id = $1
                      )
                    ORDER BY es.application_id
                    """,
                    tenant_id,
                    decision_id,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT DISTINCT es.application_id
                    FROM entity_states es
                    WHERE es.tenant_id = $1
                      AND es.application_id NOT IN (
                        SELECT application_id FROM decision_outputs
                        WHERE decision_id = $2 AND tenant_id = $1
                      )
                      AND (
                        SELECT COUNT(DISTINCT decision_id) FROM decision_outputs
                        WHERE application_id = es.application_id
                          AND decision_id = ANY($3)
                          AND tenant_id = $1
                          AND (
                            mode = 'auto_execute'
                            OR (
                              mode IN ('human_approval', 'recommend')
                              AND human_action IS NOT NULL
                            )
                          )
                      ) = $4
                    ORDER BY es.application_id
                    """,
                    tenant_id,
                    decision_id,
                    list(upstream_decision_ids),
                    len(upstream_decision_ids),
                )
        return [r["application_id"] for r in rows]

    async def get_pipeline_status(
        self,
        application_id: str,
        tenant_id: str = "default",
    ) -> dict[str, Any]:
        """Full pipeline view for one application."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            decisions = await conn.fetch(
                """
                SELECT decision_id, wave, outcome, mode, confidence, decided_at,
                       human_action
                FROM decision_outputs
                WHERE application_id = $1 AND tenant_id = $2
                  AND version = (
                    SELECT MAX(version) FROM decision_outputs d2
                    WHERE d2.application_id = decision_outputs.application_id
                      AND d2.decision_id = decision_outputs.decision_id
                      AND d2.tenant_id = decision_outputs.tenant_id
                  )
                ORDER BY wave, decided_at
                """,
                application_id,
                tenant_id,
            )
            timeline = await conn.fetch(
                """
                SELECT decision_id, wave, from_state, to_state, trigger,
                       transition_at, time_in_prev_state_seconds,
                       cumulative_elapsed_seconds, pipeline_position
                FROM decision_timeline
                WHERE application_id = $1 AND tenant_id = $2
                ORDER BY transition_at
                """,
                application_id,
                tenant_id,
            )
        decisions_list = [dict(d) for d in decisions]
        return {
            "application_id": application_id,
            "decisions": decisions_list,
            "timeline": [dict(t) for t in timeline],
            "total_decisions": len(decisions_list),
            "has_block": any(d["outcome"] == "block" for d in decisions_list),
            "pending_human": sum(
                1 for d in decisions_list
                if d["outcome"] in ("recommend", "escalate")
                and d.get("human_action") is None
                and d["mode"] == "human_approval"
            ),
        }


__all__ = ["DecisionStore", "ALL_DECISIONS"]

"""Accord — analytics endpoints (portfolio overview, funnel, agents, risk).

Aggregate read-side queries over entity_states + decision_outputs. These
scan the whole portfolio and change slowly, so each is wrapped in the
shared TTL aggregate cache (cleared on any human-review write). Reuses the
accord pool from ``api.accord.pipeline``.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from api.accord.auth import get_tenant_id

from api.accord.pipeline import PERSONAS, _f, _get_pool, _require_db, cached_agg

router = APIRouter(prefix="/api/accord/analytics", tags=["accord-analytics"])

# Normalize a stored ratio (0.769 or 76.9) to a percent expression in SQL.
_PCT = "(CASE WHEN {c} <= 1.5 THEN {c} * 100 ELSE {c} END)"


@router.get("/overview")
async def overview(tenant_id: str = Depends(get_tenant_id)) -> dict:
    _require_db()

    async def produce() -> dict:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            agg = await conn.fetchrow(
                f"""
                SELECT COUNT(*) AS total_loans,
                       COALESCE(SUM(loan_amount), 0) AS total_volume,
                       AVG(mid_credit_score) AS avg_score,
                       AVG({_PCT.format(c='ltv')}) AS avg_ltv,
                       AVG({_PCT.format(c='dti_back')}) FILTER (WHERE dti_back > 0) AS avg_dti,
                       AVG({_PCT.format(c='interest_rate')}) AS avg_rate
                FROM entity_states WHERE tenant_id = $1
                """,
                tenant_id,
            )
            appr = await conn.fetchrow(
                """
                WITH latest AS (
                    SELECT DISTINCT ON (application_id) outcome
                    FROM decision_outputs
                    WHERE tenant_id = $1 AND decision_id = 'underwriting_decision'
                    ORDER BY application_id, version DESC
                )
                SELECT COUNT(*) AS total,
                       -- underwriting emits 'recommend' (conditional approve)
                       -- rather than a literal 'allow', so an approval = not a
                       -- decline (allow OR recommend).
                       COUNT(*) FILTER (WHERE outcome IN ('allow','recommend')) AS allowed
                FROM latest
                """,
                tenant_id,
            )
        total_uw = int(appr["total"] or 0)
        return {
            "total_loans": int(agg["total_loans"] or 0),
            "total_volume": round(_f(agg["total_volume"]) or 0, 2),
            "avg_score": round(_f(agg["avg_score"]) or 0, 1),
            "avg_ltv": round(_f(agg["avg_ltv"]) or 0, 1),
            "avg_dti": round(_f(agg["avg_dti"]) or 0, 1),
            "avg_rate": round(_f(agg["avg_rate"]) or 0, 3),
            "approval_rate": round((int(appr["allowed"] or 0) / total_uw), 4) if total_uw else 0.0,
        }

    return await cached_agg(f"analytics:overview:{tenant_id}", produce)


@router.get("/funnel")
async def funnel(tenant_id: str = Depends(get_tenant_id)) -> dict:
    _require_db()

    async def produce() -> dict:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                WITH latest AS (
                    SELECT DISTINCT ON (application_id, decision_id) wave, outcome
                    FROM decision_outputs WHERE tenant_id = $1
                    ORDER BY application_id, decision_id, version DESC
                )
                SELECT wave,
                       COUNT(*) AS entered,
                       COUNT(*) FILTER (WHERE outcome IN ('allow','recommend')) AS passed,
                       COUNT(*) FILTER (WHERE outcome = 'block') AS blocked
                FROM latest GROUP BY wave ORDER BY wave
                """,
                tenant_id,
            )
        out = []
        for r in rows:
            entered = int(r["entered"] or 0)
            passed = int(r["passed"] or 0)
            out.append({
                "wave": int(r["wave"]) if r["wave"] is not None else None,
                "entered": entered,
                "passed": passed,
                "blocked": int(r["blocked"] or 0),
                "pass_rate": round(passed / entered, 4) if entered else 0.0,
            })
        return {"funnel": out}

    return await cached_agg(f"analytics:funnel:{tenant_id}", produce)


@router.get("/agents")
async def agents(tenant_id: str = Depends(get_tenant_id)) -> dict:
    _require_db()

    async def produce() -> dict:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                WITH latest AS (
                    SELECT DISTINCT ON (application_id, decision_id)
                           decision_id, outcome, human_action, decided_at, acted_at
                    FROM decision_outputs WHERE tenant_id = $1
                    ORDER BY application_id, decision_id, version DESC
                )
                SELECT decision_id,
                       COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE outcome = 'allow') AS allow_n,
                       COUNT(*) FILTER (WHERE outcome = 'block') AS block_n,
                       COUNT(*) FILTER (WHERE outcome = 'recommend') AS rec_n,
                       COUNT(*) FILTER (WHERE outcome = 'escalate') AS esc_n,
                       COUNT(*) FILTER (WHERE human_action = 'overridden') AS override_n,
                       AVG(EXTRACT(EPOCH FROM (acted_at - decided_at)))
                           FILTER (WHERE acted_at IS NOT NULL AND acted_at > decided_at) AS avg_review_sec
                FROM latest GROUP BY decision_id
                """,
                tenant_id,
            )
        out = []
        for r in rows:
            did = r["decision_id"]
            if did not in PERSONAS:
                continue
            total = int(r["total"] or 0) or 1
            rev = _f(r["avg_review_sec"])
            out.append({
                "persona": PERSONAS[did]["name"],
                "decision_id": did,
                "total": int(r["total"] or 0),
                "allow_pct": round(int(r["allow_n"] or 0) * 100 / total, 1),
                "block_pct": round(int(r["block_n"] or 0) * 100 / total, 1),
                "recommend_pct": round(int(r["rec_n"] or 0) * 100 / total, 1),
                "escalate_pct": round(int(r["esc_n"] or 0) * 100 / total, 1),
                "override_pct": round(int(r["override_n"] or 0) * 100 / total, 1),
                "avg_review_minutes": round(rev / 60, 1) if rev else None,
            })
        out.sort(key=lambda a: PERSONAS[a["decision_id"]]["wave"])
        return {"agents": out}

    return await cached_agg(f"analytics:agents:{tenant_id}", produce)


@router.get("/risk")
async def risk(tenant_id: str = Depends(get_tenant_id)) -> dict:
    _require_db()

    async def produce() -> dict:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            employers = await conn.fetch(
                """
                SELECT borrower->'employment'->>'employer_name' AS employer, COUNT(*) AS n
                FROM entity_states
                WHERE tenant_id = $1 AND borrower->'employment'->>'employer_name' IS NOT NULL
                GROUP BY 1 ORDER BY n DESC LIMIT 10
                """,
                tenant_id,
            )
            products = await conn.fetch(
                """
                SELECT loan_terms->>'loan_type' AS loan_type, COUNT(*) AS n
                FROM entity_states WHERE tenant_id = $1 AND loan_terms->>'loan_type' IS NOT NULL
                GROUP BY 1 ORDER BY n DESC
                """,
                tenant_id,
            )
            conc = await conn.fetchrow(
                f"""
                SELECT COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE {_PCT.format(c='ltv')} > 90) AS high_ltv,
                       COUNT(*) FILTER (WHERE {_PCT.format(c='dti_back')} > 43) AS high_dti
                FROM entity_states WHERE tenant_id = $1
                """,
                tenant_id,
            )
        total = int(conc["total"] or 0) or 1
        return {
            # No property geography in this dataset — geographic concentration
            # can't be computed, so it's surfaced as empty rather than faked.
            "by_geography": [],
            "by_employer": [
                {"name": r["employer"], "count": int(r["n"]),
                 "pct": round(int(r["n"]) * 100 / total, 1)}
                for r in employers
            ],
            "by_product": [
                {"name": r["loan_type"], "count": int(r["n"]),
                 "pct": round(int(r["n"]) * 100 / total, 1)}
                for r in products
            ],
            "high_ltv": int(conc["high_ltv"] or 0),
            "high_dti": int(conc["high_dti"] or 0),
            "total": int(conc["total"] or 0),
        }

    return await cached_agg(f"analytics:risk:{tenant_id}", produce)

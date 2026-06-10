"""Accord — audit endpoints (per-loan trail, adverse actions, reports,
compliance health).

Read-side over decision_outputs / decision_timeline. Literal sub-paths are
declared before /{application_id} so they aren't captured as an app id.
Reuses the accord pool from ``api.accord.pipeline``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from api.accord.pipeline import PERSONAS, _f, _get_pool, _J, _require_db, cached_agg

router = APIRouter(prefix="/api/accord/audit", tags=["accord-audit"])


# ─────────────────────────────────────────────────────────────────────
# Literal paths first
# ─────────────────────────────────────────────────────────────────────


@router.get("/adverse-action")
async def adverse_actions(
    tenant_id: str = Query("default"), limit: int = Query(100, ge=1, le=500)
) -> dict:
    """Loans the underwriter declined that owe an adverse-action notice.
    No notice-tracking table exists yet, so every decline reads as
    'pending' — the queue an examiner would want to see."""
    _require_db()
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            WITH latest AS (
                SELECT DISTINCT ON (application_id)
                       application_id, outcome, decided_at, boundary_rule
                FROM decision_outputs
                WHERE tenant_id = $1 AND decision_id = 'underwriting_decision'
                ORDER BY application_id, version DESC
            )
            SELECT l.application_id, l.decided_at, l.boundary_rule,
                   COALESCE(ap.full_name, l.application_id) AS borrower
            FROM latest l
            LEFT JOIN applications a ON a.application_id = l.application_id
            LEFT JOIN applicants ap ON ap.applicant_id = a.applicant_id
            WHERE l.outcome = 'block'
            ORDER BY l.decided_at ASC
            LIMIT $2
            """,
            tenant_id, limit,
        )
    now = datetime.now(timezone.utc)
    out = []
    for r in rows:
        decided = r["decided_at"]
        days = (now - decided).days if decided else None
        out.append({
            "application_id": r["application_id"],
            "borrower": r["borrower"],
            "block_reason": (r["boundary_rule"] or "Underwriting decline"),
            "days_since_decision": days,
            "notice_status": "pending",
        })
    return {"total": len(out), "adverse_actions": out}


@router.get("/reports")
async def reports(tenant_id: str = Query("default")) -> dict:
    _require_db()
    return await cached_agg(f"audit:reports:{tenant_id}", lambda: _reports(tenant_id))


async def _reports(tenant_id: str) -> dict:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        total = await conn.fetchval(
            "SELECT COUNT(*) FROM entity_states WHERE tenant_id = $1", tenant_id
        )
        uw_blocks = await conn.fetchval(
            """
            WITH latest AS (
                SELECT DISTINCT ON (application_id) outcome FROM decision_outputs
                WHERE tenant_id = $1 AND decision_id = 'underwriting_decision'
                ORDER BY application_id, version DESC
            )
            SELECT COUNT(*) FROM latest WHERE outcome = 'block'
            """,
            tenant_id,
        )
        overrides = await conn.fetchval(
            "SELECT COUNT(*) FROM decision_outputs WHERE tenant_id = $1 "
            "AND human_action = 'overridden'",
            tenant_id,
        )
    catalog = [
        {"id": "hmda_lar", "name": "HMDA LAR", "record_count": int(total or 0)},
        {"id": "fair_lending", "name": "Fair Lending", "record_count": int(total or 0)},
        {"id": "override_justification", "name": "Override Justification",
         "record_count": int(overrides or 0)},
        {"id": "ai_model", "name": "AI Model", "record_count": int(total or 0)},
        {"id": "examiner_package", "name": "Examiner Package",
         "record_count": int(uw_blocks or 0)},
    ]
    for c in catalog:
        c["last_run"] = None
        c["status"] = "available"
    return {"reports": catalog}


@router.get("/compliance-health")
async def compliance_health(tenant_id: str = Query("default")) -> dict:
    _require_db()
    return await cached_agg(f"audit:compliance:{tenant_id}", lambda: _compliance_health(tenant_id))


async def _compliance_health(tenant_id: str) -> dict:
    pool = await _get_pool()
    month_start = datetime.now(timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    # Single pass over the latest decision per (app, decision) — all five
    # compliance metrics computed with FILTER aggregates instead of five
    # separate full-table DISTINCT ON scans (3.6s → ~0.8s).
    async with pool.acquire() as conn:
        r = await conn.fetchrow(
            """
            WITH latest AS (
                SELECT DISTINCT ON (application_id, decision_id)
                       decision_id, outcome, mode, human_action, human_reviewer,
                       sla_seconds, actual_seconds, acted_at
                FROM decision_outputs WHERE tenant_id = $1
                ORDER BY application_id, decision_id, version DESC
            )
            SELECT
                COUNT(*) FILTER (WHERE decision_id = 'compliance_check') AS comp_total,
                COUNT(*) FILTER (WHERE decision_id = 'compliance_check' AND outcome = 'allow') AS comp_clean,
                COUNT(*) FILTER (WHERE decision_id = 'underwriting_decision' AND outcome = 'block') AS adverse_pending,
                COUNT(*) FILTER (WHERE human_action = 'overridden' AND acted_at >= $2) AS overrides_month,
                COUNT(*) FILTER (WHERE sla_seconds > 0) AS sla_measured,
                COUNT(*) FILTER (WHERE sla_seconds > 0 AND actual_seconds <= sla_seconds) AS sla_met,
                COUNT(*) FILTER (WHERE mode = 'human_approval'
                                 AND (human_reviewer IS NULL OR human_reviewer = 'system')) AS seg_flags
            FROM latest
            """,
            tenant_id, month_start,
        )
    ctotal = int(r["comp_total"] or 0) or 1
    measured = int(r["sla_measured"] or 0) or 1
    return {
        "hmda_pct": round(int(r["comp_clean"] or 0) * 100 / ctotal, 1),
        "adverse_pending": int(r["adverse_pending"] or 0),
        "overrides": int(r["overrides_month"] or 0),
        "sla_pct": round(int(r["sla_met"] or 0) * 100 / measured, 1),
        "segregation_flags": int(r["seg_flags"] or 0),
    }


# ─────────────────────────────────────────────────────────────────────
# Per-loan audit trail  (declared LAST so it doesn't shadow the literals)
# ─────────────────────────────────────────────────────────────────────


@router.get("/{application_id}")
async def loan_audit(application_id: str, tenant_id: str = Query("default")) -> dict:
    _require_db()
    pool = await _get_pool()
    async with pool.acquire() as conn:
        ver_rows = await conn.fetch(
            """
            SELECT decision_id, version, outcome, mode, human_action,
                   human_reviewer, human_override_reason, decided_at, acted_at, stale,
                   sla_seconds, actual_seconds
            FROM decision_outputs WHERE application_id = $1 AND tenant_id = $2
            ORDER BY decided_at ASC, decision_id, version
            """,
            application_id, tenant_id,
        )
        tl_rows = await conn.fetch(
            """
            SELECT decision_id, from_state, to_state, trigger, transition_at, waiting_on
            FROM decision_timeline WHERE application_id = $1 AND tenant_id = $2
            ORDER BY transition_at ASC
            """,
            application_id, tenant_id,
        )
    if not ver_rows and not tl_rows:
        raise HTTPException(404, f"No audit trail for {application_id}")

    versions = [
        {
            "decision_id": r["decision_id"],
            "persona": PERSONAS.get(r["decision_id"], {}).get("name", r["decision_id"]),
            "version": r["version"],
            "outcome": r["outcome"],
            "mode": r["mode"],
            "human_action": r["human_action"],
            "reviewer": r["human_reviewer"],
            "override_reason": r["human_override_reason"],
            "stale": bool(r["stale"]) if r["stale"] is not None else False,
            "decided_at": r["decided_at"].isoformat() if r["decided_at"] else None,
            "acted_at": r["acted_at"].isoformat() if r["acted_at"] else None,
        }
        for r in ver_rows
    ]

    authority_chain = []
    for r in tl_rows:
        meta = _J(r["waiting_on"])
        actor = (meta.get("reverted_by") or meta.get("requested_by")) if isinstance(meta, dict) else None
        authority_chain.append({
            "decision_id": r["decision_id"],
            "from": r["from_state"],
            "to": r["to_state"],
            "trigger": r["trigger"],
            "by": actor,
            "at": r["transition_at"].isoformat() if r["transition_at"] else None,
        })

    # SLA per latest decision version.
    latest_by_dec: dict[str, Any] = {}
    for r in ver_rows:
        latest_by_dec[r["decision_id"]] = r  # ordered asc → last wins = latest version
    sla = []
    for did, r in latest_by_dec.items():
        slas, act = _f(r["sla_seconds"]), _f(r["actual_seconds"])
        sla.append({
            "decision_id": did,
            "persona": PERSONAS.get(did, {}).get("name", did),
            "sla_seconds": slas,
            "actual_seconds": act,
            "met": (act is not None and slas is not None and slas > 0 and act <= slas),
        })

    return {
        "application_id": application_id,
        "versions": versions,
        "authority_chain": authority_chain,
        "sla": sla,
    }

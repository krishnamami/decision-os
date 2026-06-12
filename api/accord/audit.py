"""Accord — audit endpoints (per-loan trail, adverse actions, reports,
compliance health).

Read-side over decision_outputs / decision_timeline. Literal sub-paths are
declared before /{application_id} so they aren't captured as an app id.
Reuses the accord pool from ``api.accord.pipeline``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from api.accord.auth import get_current_user, get_tenant_id

from api.accord.pipeline import PERSONAS, _f, _get_pool, _J, _require_db, cached_agg

router = APIRouter(prefix="/api/accord/audit", tags=["accord-audit"])


# ─────────────────────────────────────────────────────────────────────
# Literal paths first
# ─────────────────────────────────────────────────────────────────────


@router.get("/adverse-action")
async def adverse_actions(
    tenant_id: str = Depends(get_tenant_id), limit: int = Query(100, ge=1, le=500)
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
async def reports(tenant_id: str = Depends(get_tenant_id)) -> dict:
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


@router.get("/reports/{report_id}/data")
async def report_data(report_id: str, user: dict = Depends(get_current_user)) -> dict:
    """Real, tenant-scoped rows for a governance report — the frontend turns
    {columns, rows} into a CSV/PDF download. Managers + compliance only."""
    if user.get("role") not in ("admin", "manager", "compliance"):
        raise HTTPException(403, "Manager or compliance access required")
    _require_db()
    tid = user["tenant_id"]
    pool = await _get_pool()
    async with pool.acquire() as conn:
        if report_id == "hmda_lar":
            columns = ["Application", "Borrower", "Loan Amount", "Loan Type", "Credit Score", "LTV %", "DTI %", "Status", "Action Taken"]
            recs = await conn.fetch(
                "SELECT es.application_id, COALESCE(ap.full_name, es.application_id) AS borrower, es.loan_amount, "
                "a.loan_type, es.mid_credit_score, es.ltv, es.dti_back, es.loan_status "
                "FROM entity_states es LEFT JOIN applications a ON a.application_id=es.application_id "
                "LEFT JOIN applicants ap ON ap.applicant_id=a.applicant_id WHERE es.tenant_id=$1 ORDER BY es.application_id",
                tid,
            )
            act = {"decided": "Approved", "funded": "Loan originated", "halted": "Application denied",
                   "pending_borrower": "Incomplete", "active": "In process"}
            rows = [[r["application_id"], r["borrower"], _f(r["loan_amount"]), r["loan_type"],
                     r["mid_credit_score"], _f(r["ltv"]), _f(r["dti_back"]), r["loan_status"],
                     act.get(r["loan_status"], "In process")] for r in recs]
        elif report_id == "override_justification":
            columns = ["Application", "Decision", "AI Outcome", "Reviewer", "Justification", "When"]
            recs = await conn.fetch(
                "SELECT application_id, decision_id, outcome, human_reviewer, human_override_reason, acted_at "
                "FROM decision_outputs WHERE tenant_id=$1 AND human_action='overridden' ORDER BY acted_at DESC",
                tid,
            )
            rows = [[r["application_id"], PERSONAS.get(r["decision_id"], {}).get("name", r["decision_id"]),
                     r["outcome"], r["human_reviewer"], r["human_override_reason"],
                     r["acted_at"].isoformat() if r["acted_at"] else ""] for r in recs]
        elif report_id == "ai_model":
            columns = ["Agent", "Decisions", "Allow %", "Block %", "Override %", "Avg Confidence %"]
            recs = await conn.fetch(
                "SELECT decision_id, count(*) n, "
                "round((100.0*count(*) FILTER (WHERE outcome='allow')/count(*))::numeric,1) allow_pct, "
                "round((100.0*count(*) FILTER (WHERE outcome='block')/count(*))::numeric,1) block_pct, "
                "round((100.0*count(*) FILTER (WHERE human_action='overridden')/count(*))::numeric,1) ov_pct, "
                "round((100.0*avg(confidence))::numeric,1) conf "
                "FROM decision_outputs WHERE tenant_id=$1 GROUP BY decision_id ORDER BY decision_id",
                tid,
            )
            rows = [[PERSONAS.get(r["decision_id"], {}).get("name", r["decision_id"]), int(r["n"]),
                     float(r["allow_pct"] or 0), float(r["block_pct"] or 0), float(r["ov_pct"] or 0),
                     float(r["conf"] or 0)] for r in recs]
        elif report_id == "fair_lending":
            columns = ["Segment (loan type)", "Loans", "Approved", "Approval Rate %", "Disparate Impact"]
            recs = await conn.fetch(
                "SELECT a.loan_type AS seg, count(*) n, "
                "count(*) FILTER (WHERE es.loan_status IN ('decided','funded')) approved "
                "FROM entity_states es LEFT JOIN applications a ON a.application_id=es.application_id "
                "WHERE es.tenant_id=$1 GROUP BY a.loan_type ORDER BY n DESC",
                tid,
            )
            tot = sum(int(r["n"]) for r in recs)
            apr = sum(int(r["approved"]) for r in recs)
            overall = apr / tot if tot else 0
            rows = []
            for r in recs:
                n, ap_ = int(r["n"]), int(r["approved"])
                rate = ap_ / n if n else 0
                flag = ("⚠ review — rate deviates >15%"
                        if overall and n >= 5 and abs(rate - overall) / max(overall, 0.01) > 0.15
                        else "No disparate impact")
                rows.append([r["seg"] or "unknown", n, ap_, round(rate * 100, 1), flag])
        else:  # examiner_package (or unknown) — loan-level decision chain summary
            columns = ["Application", "Status", "AI Decisions", "Human Actions", "Overrides"]
            recs = await conn.fetch(
                "SELECT es.application_id, es.loan_status, "
                "(SELECT count(DISTINCT decision_id) FROM decision_outputs d WHERE d.application_id=es.application_id AND d.tenant_id=$1) ai, "
                "(SELECT count(*) FROM decision_outputs d WHERE d.application_id=es.application_id AND d.tenant_id=$1 AND d.human_action IS NOT NULL) ha, "
                "(SELECT count(*) FROM decision_outputs d WHERE d.application_id=es.application_id AND d.tenant_id=$1 AND d.human_action='overridden') ov "
                "FROM entity_states es WHERE es.tenant_id=$1 ORDER BY es.application_id",
                tid,
            )
            rows = [[r["application_id"], r["loan_status"], int(r["ai"]), int(r["ha"]), int(r["ov"])] for r in recs]
    return {"report_id": report_id, "columns": columns, "rows": rows, "count": len(rows)}


@router.get("/compliance-health")
async def compliance_health(tenant_id: str = Depends(get_tenant_id)) -> dict:
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
async def loan_audit(application_id: str, tenant_id: str = Depends(get_tenant_id)) -> dict:
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

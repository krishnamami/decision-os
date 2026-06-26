"""Accord — audit endpoints (per-loan trail, adverse actions, reports,
compliance health).

Read-side over decision_outputs / decision_timeline. Literal sub-paths are
declared before /{application_id} so they aren't captured as an app id.
Reuses the accord pool from ``api.accord.pipeline``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from api.accord.auth import get_current_user, get_tenant_id, require_permission

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
async def report_data(
    report_id: str,
    user: dict = Depends(require_permission("export_reports")),
) -> dict:
    """Real, tenant-scoped rows for a governance report — the frontend turns
    {columns, rows} into a CSV/PDF download. Gated by export_reports
    (senior_uw + compliance + admin)."""
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


# HMDA LAR fields the platform does not capture per loan (demographics +
# geocoding) — genuinely absent from the record, not fabricated.
_HMDA_NOT_CAPTURED = ["hmda_ethnicity", "hmda_race", "hmda_sex",
                      "hmda_tract_number", "hmda_county_code", "hmda_msa_md"]


@router.get("/hmda-incomplete")
async def hmda_incomplete(user: dict = Depends(get_current_user)) -> dict:
    """Drill-down behind the HMDA Completeness KPI (12 CFR §1003). Completeness is
    the seeded all_hmda_fields_complete flag (no per-field LAR values are stored).
    For each flagged loan, missing fields are derived from the REAL record where
    evaluable (income / loan amount / purpose / occupancy / rate) plus the LAR
    fields the platform doesn't capture — all true absences, never fabricated."""
    _require_db()
    tenant_id = user["tenant_id"]
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT es.application_id, es.borrower, es.loan_amount, es.interest_rate,
                   a.loan_purpose, a.occupancy, ap.full_name,
                   v.all_hmda_fields_complete AS hmda_complete
            FROM entity_states es
            LEFT JOIN vw_compliance_check_context v
                   ON v.application_id = es.application_id AND v.tenant_id = es.tenant_id
            LEFT JOIN applications a ON a.application_id = es.application_id
            LEFT JOIN applicants ap ON ap.applicant_id = es.borrower->>'applicant_id'
            WHERE es.tenant_id = $1
            ORDER BY es.application_id
            """,
            tenant_id,
        )

    total = len(rows)
    complete = 0
    loans: list[dict] = []
    for r in rows:
        if r["hmda_complete"]:
            complete += 1
            continue
        b = _J(r["borrower"]) or {}
        inc = b.get("income") or {}
        missing: list[str] = []
        if not (inc.get("verified_income_annual") or inc.get("stated_income_annual")):
            missing.append("hmda_income")
        if r["loan_amount"] is None:
            missing.append("hmda_loan_amount")
        if not r["loan_purpose"]:
            missing.append("hmda_loan_purpose")
        if not r["occupancy"]:
            missing.append("hmda_occupancy_type")
        if r["interest_rate"] is None:
            missing.append("hmda_rate_spread")
        missing += _HMDA_NOT_CAPTURED
        loans.append({
            "application_id": r["application_id"],
            "borrower_name": r["full_name"] or b.get("applicant_id") or r["application_id"],
            "missing_fields": missing,
            "missing_count": len(missing),
        })

    loans.sort(key=lambda x: x["missing_count"], reverse=True)
    return {
        "filing_deadline": "February 28, 2027",
        "total": total,
        "complete": complete,
        "incomplete": len(loans),
        "pct": round(complete * 100 / total) if total else 0,
        "note": ("Borrower demographic (ethnicity / race / sex) and HMDA geocoding "
                 "(census tract, county, MSA/MD) fields are collected at application "
                 "and are not captured in these records."),
        "loans": loans,
    }


# ─────────────────────────────────────────────────────────────────────
# CF-A — HMDA LAR submission file + CFPB edit checks (read-only export)
# ─────────────────────────────────────────────────────────────────────
async def _fetch_hmda_records(tenant_id: str, year: Optional[int]) -> list:
    _require_db()
    pool = await _get_pool()
    async with pool.acquire() as conn:
        if year:
            rows = await conn.fetch(
                "SELECT * FROM hmda_lar WHERE tenant_id=$1 AND hmda_reportable=true "
                "AND EXTRACT(YEAR FROM action_taken_date)=$2 ORDER BY application_id",
                tenant_id, year)
        else:
            rows = await conn.fetch(
                "SELECT * FROM hmda_lar WHERE tenant_id=$1 AND hmda_reportable=true "
                "ORDER BY application_id", tenant_id)
    return [dict(r) for r in rows]


def _institution_meta(user: dict) -> dict:
    tid = user.get("tenant_id", "")
    return {"tenant_id": tid, "lei": (user.get("lei") or "").strip(),
            "institution_name": user.get("institution_name") or tid,
            "contact_email": user.get("email", "")}


@router.get("/hmda/lar-file")
async def hmda_lar_file(year: Optional[int] = Query(None),
                        user: dict = Depends(get_current_user)):
    """Download the pipe-delimited HMDA LAR submission file (FFIEC FIG format) for
    the tenant. Admin/compliance only. Read-only; CFPB upload is a manual step."""
    if user.get("role") not in ("admin", "compliance", "super_admin"):
        raise HTTPException(403, "Admin or compliance access required")
    from fastapi import Response
    from core.compliance.hmda_lar_file import generate_lar_file
    records = await _fetch_hmda_records(user["tenant_id"], year)
    cal_year = year or 2024
    text, missing = generate_lar_file(records, _institution_meta(user), cal_year)
    return Response(
        content=text, media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="hmda_lar_{user["tenant_id"]}_{cal_year}.txt"',
                 "X-HMDA-Records": str(len(records)),
                 "X-HMDA-Records-With-Missing-Fields": str(len(missing))})


@router.get("/hmda/edit-checks")
async def hmda_edit_checks(year: Optional[int] = Query(None),
                           user: dict = Depends(get_current_user)) -> dict:
    """Run the CFPB edit checks (S/V/Q/M) over the tenant's LAR records and return a
    structured report (submission_ready + errors/warnings/infos). Admin/compliance."""
    if user.get("role") not in ("admin", "compliance", "super_admin"):
        raise HTTPException(403, "Admin or compliance access required")
    from core.compliance.hmda_lar_file import generate_lar_file, parse_lar_rows
    from core.compliance.hmda_edit_checks import run_edit_checks
    records = await _fetch_hmda_records(user["tenant_id"], year)
    text, missing = generate_lar_file(records, _institution_meta(user), year or 2024)
    report = run_edit_checks(records, parse_lar_rows(text))
    report["missing_fields_report"] = missing
    return report


# ─────────────────────────────────────────────────────────────────────
# CF-B — ECOA 12 CFR 202.15 fair-lending self-testing program (privileged)
# ─────────────────────────────────────────────────────────────────────
@router.get("/fair-lending/self-test")
async def fair_lending_self_test(year: Optional[int] = Query(None),
                                 user: dict = Depends(get_current_user)) -> dict:
    """Run the ECOA 12 CFR 202.15 fair-lending self-test (aggregate 4/5 + peer-group
    matched analysis) and return the PRIVILEGED report. Admin/compliance only;
    post-decision read-only. Do not disclose without legal review."""
    if user.get("role") not in ("admin", "compliance", "super_admin"):
        raise HTTPException(403, "Admin or compliance access required")
    _require_db()
    from core.compliance.fair_lending_self_test import (
        FairLendingSelfTest, fetch_self_test_data)
    tenant_id = user["tenant_id"]
    pool = await _get_pool()
    async with pool.acquire() as conn:
        hmda, joined = await fetch_self_test_data(conn, tenant_id, year)
        exc = await conn.fetch(
            "SELECT application_id, granted, status FROM loan_exceptions "
            "WHERE tenant_id=$1 AND status IN ('granted','denied')", tenant_id)
    report = FairLendingSelfTest().run(
        hmda_rows=hmda, joined_rows=joined, exception_rows=[dict(r) for r in exc],
        period_start=f"{year}-01-01" if year else "all", run_by=user.get("email", "system"),
        period_end=f"{year}-12-31" if year else "all", tenant_id=tenant_id)
    return report


# ─────────────────────────────────────────────────────────────────────
# CF-C — CRA community reinvestment assessment (banks/credit unions only)
# ─────────────────────────────────────────────────────────────────────
@router.get("/cra/assessment")
async def cra_assessment(year: Optional[int] = Query(None),
                         area_median_income: Optional[float] = Query(None),
                         user: dict = Depends(get_current_user)) -> dict:
    """CRA community-reinvestment assessment (12 CFR 25/228). Banks/credit unions
    only; post-decision read-only. Returns insufficient_data until census tracts +
    FFIEC tract-income + AMI are loaded. Admin/compliance only."""
    if user.get("role") not in ("admin", "compliance", "super_admin"):
        raise HTTPException(403, "Admin or compliance access required")
    _require_db()
    from core.compliance.cra_assessment import CRAAssessment, fetch_cra_data
    tenant_id = user["tenant_id"]
    pool = await _get_pool()
    async with pool.acquire() as conn:
        loans, institution_type = await fetch_cra_data(conn, tenant_id, year)
    return CRAAssessment().assess(
        loans=loans, area_median_income=area_median_income,
        tract_incomes=None,  # future: load from the FFIEC Census File
        institution_type=institution_type, tenant_id=tenant_id,
        period=str(year) if year else "all")


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

"""Accord — Rules Dashboard API (the three-layer trust surface).

Read the regulatory / agency / customer-overlay layers, edit the overlay with
guardrails (no value may drop below a hard regulatory/agency minimum), version
+ approve changes, look up which version governed a given date, and surface data
freshness + agency change alerts. Reuses the accord asyncpg pool.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from api.accord.auth import get_current_user, get_tenant_id
from api.accord.pipeline import _get_pool, _require_db

router = APIRouter(prefix="/api/accord/rules", tags=["accord-rules"])

# Which agencies a tenant's programs pull guidelines from.
PROGRAM_AGENCIES: dict[str, list[str]] = {
    "conventional": ["fannie", "freddie"],
    "fha": ["fha"],
    "va": ["va"],
    "usda": ["usda"],
    "jumbo": [],
    "non_qm": [],
}


def _jsonb(v: Any) -> Any:
    """asyncpg returns jsonb as text — decode it (pass through dict/list)."""
    if isinstance(v, (dict, list)) or v is None:
        return v
    try:
        return json.loads(v)
    except (TypeError, ValueError):
        return v


def _iso(v: Any) -> Optional[str]:
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return v


def _date(v):
    return date.fromisoformat(v) if isinstance(v, str) and v else v


def _agencies_for(programs: list[str]) -> set[str]:
    out: set[str] = set()
    for p in programs:
        out.update(PROGRAM_AGENCIES.get(p, []))
    return out


def validate_overlay(rules: dict, programs: list[str]) -> tuple[list[str], list[str]]:
    """Return (hard_errors, soft_warnings) for a proposed overlay.

    Hard floors block the change; soft warnings just flag it for the approver.
    """
    errors: list[str] = []
    warnings: list[str] = []

    credit = (rules.get("credit") or {}).get("min_score")
    if isinstance(credit, (int, float)):
        if "fha" in programs and credit < 580:
            errors.append(f"Credit floor {credit} is below the FHA minimum of 580 for your FHA program")
        elif credit < 500:
            errors.append(f"Credit floor {credit} is below the FHA absolute minimum of 500")
        if credit < 620:
            warnings.append(f"Credit floor {credit} is below the Fannie guideline of 620")

    dti = (rules.get("dti") or {}).get("back_max")
    if isinstance(dti, (int, float)):
        if dti > 57:
            errors.append(f"DTI {dti}% exceeds the hard maximum of 57%")
        elif dti > 43:
            warnings.append(f"DTI {dti}% exceeds the QM safe-harbor limit of 43%")

    ltv = (rules.get("ltv") or {}).get("max")
    if isinstance(ltv, (int, float)) and ltv > 97:
        errors.append(f"LTV {ltv}% exceeds the Fannie conventional maximum of 97%")

    return errors, warnings


async def _active_version(conn, tenant_id: str):
    return await conn.fetchrow(
        "SELECT * FROM tenant_rules WHERE tenant_id=$1 AND status='active' ORDER BY version DESC LIMIT 1",
        tenant_id,
    )


def _version_row(r, names: dict[str, str]) -> dict:
    return {
        "rule_version_id": str(r["rule_version_id"]),
        "version": r["version"],
        "status": r["status"],
        "rules": _jsonb(r["rules"]),
        "programs": _jsonb(r["programs"]),
        "changes_summary": r["changes_summary"],
        "change_reason": r["change_reason"],
        "created_by": names.get(str(r["created_by"])) if r["created_by"] else None,
        "approved_by": names.get(str(r["approved_by"])) if r["approved_by"] else None,
        "effective_from": _iso(r["effective_from"]),
        "effective_to": _iso(r["effective_to"]),
        "created_at": _iso(r["created_at"]),
        "approved_at": _iso(r["approved_at"]),
        "change_type": r.get("change_type"),
        "scheduled_for": _iso(r.get("scheduled_for")),
        "expires_at": _iso(r.get("expires_at")),
        "rolled_back_from": r.get("rolled_back_from"),
        "pipeline_policy": r.get("pipeline_policy"),
        "ratified_by": names.get(str(r.get("ratified_by"))) if r.get("ratified_by") else None,
        "ratified_at": _iso(r.get("ratified_at")),
        "emergency_type": r.get("emergency_type"),
    }


async def _user_names(conn, tenant_id: str) -> dict[str, str]:
    rows = await conn.fetch("SELECT user_id, name FROM users WHERE tenant_id=$1", tenant_id)
    return {str(r["user_id"]): r["name"] for r in rows}


# ── 1. All three layers for the current tenant ──────────────────────
@router.get("")
async def get_rules(tenant_id: str = Depends(get_tenant_id)) -> dict:
    _require_db()
    pool = await _get_pool()
    async with pool.acquire() as conn:
        active = await _active_version(conn, tenant_id)
        programs = _jsonb(active["programs"]) if active else ["conventional", "fha"]
        agencies = _agencies_for(programs)

        reg = await conn.fetch("SELECT * FROM regulatory_rules WHERE is_active=true ORDER BY category, authority")
        if agencies:
            agc = await conn.fetch(
                "SELECT * FROM agency_guidelines WHERE is_active=true AND agency = ANY($1::text[]) ORDER BY category, agency",
                list(agencies),
            )
        else:
            agc = await conn.fetch("SELECT * FROM agency_guidelines WHERE is_active=true ORDER BY category, agency")
        freshness = await conn.fetch("SELECT * FROM data_source_status ORDER BY source_name")
        names = await _user_names(conn, tenant_id)
        scheduled = await conn.fetch(
            "SELECT * FROM tenant_rules WHERE tenant_id=$1 AND status='scheduled' ORDER BY scheduled_for", tenant_id)
        shadow = await conn.fetchrow(
            "SELECT * FROM tenant_rules WHERE tenant_id=$1 AND status='shadow' ORDER BY version DESC LIMIT 1", tenant_id)
        exam = await conn.fetchrow(
            "SELECT * FROM examination_periods WHERE tenant_id=$1 AND is_active=true ORDER BY started_at DESC LIMIT 1", tenant_id)

    errors, warnings = validate_overlay(_jsonb(active["rules"]), programs) if active else ([], [])
    expiring = _expiring_waivers(_jsonb(active["rules"]) if active else {})

    return {
        "regulatory": [{
            "rule_id": str(r["rule_id"]), "authority": r["authority"], "state_code": r["state_code"],
            "category": r["category"], "rule_name": r["rule_name"], "rule_value": _jsonb(r["rule_value"]),
            "display_value": r["display_value"], "description": r["description"], "citation": r["citation"],
            "source_url": r["source_url"], "effective_date": _iso(r["effective_date"]),
        } for r in reg],
        "agency": [{
            "guideline_id": str(r["guideline_id"]), "agency": r["agency"], "category": r["category"],
            "guideline_name": r["guideline_name"], "guideline_value": _jsonb(r["guideline_value"]),
            "display_value": r["display_value"], "description": r["description"], "conditions": r["conditions"],
            "citation": r["citation"], "source_url": r["source_url"], "effective_date": _iso(r["effective_date"]),
            "last_verified": _iso(r["last_verified"]), "verified_by": r["verified_by"],
        } for r in agc],
        "tenant": _version_row(active, names) if active else None,
        "data_freshness": [_freshness_row(r) for r in freshness],
        "validation": {"all_above_regulatory": not errors, "errors": errors, "warnings": warnings},
        "scheduled": [_version_row(r, names) for r in scheduled],
        "shadow": _version_row(shadow, names) if shadow else None,
        "examination": {
            "active": True, "examiner": exam["examiner"], "reason": exam["reason"],
            "started_at": _iso(exam["started_at"]),
        } if exam else {"active": False},
        "expiring": expiring,
    }


def _expiring_waivers(rules: dict) -> list[dict]:
    """Surface waiver programs (in the overlay JSON) that have an expiry date,
    with a days-remaining + severity for the dashboard warning."""
    out: list[dict] = []
    today = date.today()
    for w in (rules or {}).get("waivers", []) or []:
        exp = w.get("expires")
        if not exp:
            continue
        try:
            days = (date.fromisoformat(exp) - today).days
        except ValueError:
            continue
        out.append({
            "name": w.get("name"), "field": w.get("field"), "value": w.get("value"),
            "normal": w.get("normal"), "expires": exp, "days_remaining": days,
            "severity": "red" if days <= 1 else "amber" if days <= 7 else "info" if days <= 30 else "ok",
        })
    return out


# ── 2. Version history ──────────────────────────────────────────────
@router.get("/history")
async def get_history(tenant_id: str = Depends(get_tenant_id)) -> dict:
    _require_db()
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM tenant_rules WHERE tenant_id=$1 ORDER BY version DESC", tenant_id
        )
        names = await _user_names(conn, tenant_id)
    return {"versions": [_version_row(r, names) for r in rows]}


# ── 3. Propose an overlay change (admin/manager) → pending_approval ──
class RulesUpdate(BaseModel):
    rules: dict
    change_reason: str
    changes_summary: Optional[str] = None
    programs: Optional[list[str]] = None


@router.put("")
async def update_rules(body: RulesUpdate, user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") not in ("admin", "manager"):
        raise HTTPException(403, "Admin or manager access required to edit rules")
    _require_db()
    tenant_id = user["tenant_id"]
    if not (body.change_reason or "").strip():
        raise HTTPException(422, "A reason for the change is required")

    pool = await _get_pool()
    async with pool.acquire() as conn:
        await _check_not_frozen(conn, tenant_id)
        active = await _active_version(conn, tenant_id)
        programs = body.programs or (_jsonb(active["programs"]) if active else ["conventional", "fha"])
        errors, warnings = validate_overlay(body.rules, programs)
        if errors:
            raise HTTPException(400, errors[0])

        # Auto-run the boundary validation suite on the proposed rules — a bad
        # rule that slips past the guardrail can never go live.
        from api.accord.validation import run_validation
        val = await run_validation(tenant_id, proposed_rules=body.rules, programs=programs)
        if val["failed"] > 0:
            fails = [t for t in val["tests"] if not t["passed"]][:3]
            detail = "; ".join(f"{t['id']}: expected {t['expected']} but got {t['actual']}" for t in fails)
            raise HTTPException(400, f"Rule change cannot be activated — {val['failed']} validation test(s) failed: {detail}")

        next_version = (await conn.fetchval(
            "SELECT COALESCE(MAX(version), 0) + 1 FROM tenant_rules WHERE tenant_id=$1", tenant_id)) or 1
        # Only one pending draft at a time — replace any prior pending.
        await conn.execute(
            "DELETE FROM tenant_rules WHERE tenant_id=$1 AND status='pending_approval'", tenant_id)
        new_id = await conn.fetchval(
            "INSERT INTO tenant_rules (tenant_id, version, status, rules, programs, changes_summary, change_reason, created_by) "
            "VALUES ($1,$2,'pending_approval',$3::jsonb,$4::jsonb,$5,$6,$7) RETURNING rule_version_id",
            tenant_id, next_version, json.dumps(body.rules), json.dumps(programs),
            body.changes_summary, body.change_reason, _uuid(user.get("user_id")),
        )
    return {"rule_version_id": str(new_id), "version": next_version, "status": "pending_approval", "warnings": warnings}


# ── 4. Approve the pending change (admin only) → active ─────────────
@router.post("/approve")
async def approve_rules(payload: dict = Body(default={}), user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin access required to approve rule changes")
    _require_db()
    tenant_id = user["tenant_id"]
    pool = await _get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            pending = await conn.fetchrow(
                "SELECT * FROM tenant_rules WHERE tenant_id=$1 AND status='pending_approval' ORDER BY version DESC LIMIT 1",
                tenant_id)
            if pending is None:
                raise HTTPException(404, "No pending rule change to approve")
            now = datetime.utcnow()  # DB timestamps are tz-naive
            await conn.execute(
                "UPDATE tenant_rules SET status='superseded', effective_to=$1 WHERE tenant_id=$2 AND status='active'",
                now, tenant_id)
            await conn.execute(
                "UPDATE tenant_rules SET status='active', approved_by=$1, approved_at=$2, effective_from=$2 "
                "WHERE rule_version_id=$3",
                _uuid(user.get("user_id")), now, pending["rule_version_id"])
    return {"ok": True, "version": pending["version"], "status": "active"}


# ── 6. Which version governed a given date (examiner lookup) ────────
@router.get("/lookup")
async def lookup(date: str, tenant_id: str = Depends(get_tenant_id)) -> dict:
    _require_db()
    try:
        target = datetime.fromisoformat(date.replace("Z", "+00:00"))
        if target.tzinfo is not None:  # DB timestamps are tz-naive
            target = target.astimezone(timezone.utc).replace(tzinfo=None)
    except ValueError:
        raise HTTPException(422, "date must be ISO-8601 (e.g. 2026-06-03)")
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM tenant_rules WHERE tenant_id=$1 AND status IN ('active','superseded') "
            "AND effective_from <= $2 AND (effective_to IS NULL OR effective_to > $2) "
            "ORDER BY version DESC LIMIT 1",
            tenant_id, target)
        names = await _user_names(conn, tenant_id)
    if row is None:
        return {"found": False, "date": date, "message": "No rule version was active on that date."}
    return {"found": True, "date": date, "version": row["version"], "rules": _version_row(row, names)}


# ── 7. Data freshness ───────────────────────────────────────────────
def _freshness_row(r) -> dict:
    return {
        "source_id": r["source_id"], "source_name": r["source_name"], "source_url": r["source_url"],
        "last_download": _iso(r["last_download"]), "last_success": _iso(r["last_success"]),
        "record_count": r["record_count"], "status": r["status"], "next_scheduled": _iso(r["next_scheduled"]),
        "error_message": r["error_message"],
    }


@router.get("/data-freshness")
async def data_freshness(tenant_id: str = Depends(get_tenant_id)) -> dict:
    _require_db()
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM data_source_status ORDER BY source_name")
    sources = [_freshness_row(r) for r in rows]
    stale = [s for s in sources if s["status"] != "ok"]
    return {"sources": sources, "all_ok": not stale, "stale": stale}


# ── 8. Agency / regulatory change alerts ────────────────────────────
@router.get("/alerts")
async def alerts(tenant_id: str = Depends(get_tenant_id)) -> dict:
    _require_db()
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM rule_change_alerts WHERE status != 'dismissed' ORDER BY published_date DESC NULLS LAST")
    items = [{
        "alert_id": str(r["alert_id"]), "source": r["source"], "title": r["title"],
        "description": r["description"], "url": r["url"], "published_date": _iso(r["published_date"]),
        "status": r["status"],
    } for r in rows]
    return {"alerts": items, "new_count": sum(1 for i in items if i["status"] == "new")}


def _uuid(v: Any):
    from uuid import UUID
    if v is None:
        return None
    try:
        return UUID(str(v))
    except (ValueError, TypeError):
        return None


# ════════════════════════════════════════════════════════════════════
# Advanced versioning — rollback, scheduling, shadow, emergency,
# examination freeze, retrospective, reconstruction, pipeline policy.
# ════════════════════════════════════════════════════════════════════

def _require(user: dict, *roles: str) -> None:
    if user.get("role") not in roles:
        raise HTTPException(403, f"Requires one of: {', '.join(roles)}")


async def _examination(conn, tenant_id: str):
    return await conn.fetchrow(
        "SELECT * FROM examination_periods WHERE tenant_id=$1 AND is_active=true ORDER BY started_at DESC LIMIT 1",
        tenant_id)


async def _check_not_frozen(conn, tenant_id: str) -> None:
    exam = await _examination(conn, tenant_id)
    if exam:
        when = exam["started_at"].strftime("%b %d, %Y") if exam["started_at"] else "an earlier date"
        raise HTTPException(
            403,
            f"Rule changes are frozen during active examination. Examination: {exam['examiner']} "
            f"(started {when}). Emergency overrides still available with extra documentation.")


async def _next_version(conn, tenant_id: str) -> int:
    return (await conn.fetchval("SELECT COALESCE(MAX(version),0)+1 FROM tenant_rules WHERE tenant_id=$1", tenant_id)) or 1


def _norm(v, pct=False):
    if v is None:
        return None
    v = float(v)
    if pct and v <= 1:
        v *= 100
    return v


def _evaluate(rules: dict, credit, dti, ltv) -> str:
    """Pragmatic loan verdict under a rule set: allow unless a hard threshold fails."""
    c = (rules.get("credit") or {}).get("min_score")
    d = (rules.get("dti") or {}).get("back_max")
    l = (rules.get("ltv") or {}).get("max")
    credit, dti, ltv = _norm(credit), _norm(dti, True), _norm(ltv, True)
    if c is not None and credit is not None and credit < c:
        return "block"
    if d is not None and dti is not None and dti > d:
        return "block"
    if l is not None and ltv is not None and ltv > l:
        return "block"
    return "allow"


async def _active_loans(conn, tenant_id: str):
    return await conn.fetch(
        """SELECT es.application_id, es.dti_back, es.mid_credit_score, es.ltv, es.loan_status, ap.full_name
           FROM entity_states es
           LEFT JOIN applications a ON a.application_id = es.application_id
           LEFT JOIN applicants ap ON ap.applicant_id = a.applicant_id
           WHERE es.tenant_id=$1 AND es.loan_status='active'""",
        tenant_id)


async def _pipeline_impact(conn, tenant_id: str, new_rules: dict) -> dict:
    rows = await _active_loans(conn, tenant_id)
    count = 0
    examples: list[dict] = []
    nc = (new_rules.get("credit") or {}).get("min_score")
    nd = (new_rules.get("dti") or {}).get("back_max")
    nl = (new_rules.get("ltv") or {}).get("max")
    for r in rows:
        credit, dti, ltv = _norm(r["mid_credit_score"]), _norm(r["dti_back"], True), _norm(r["ltv"], True)
        reason = None
        if nc is not None and credit is not None and credit < nc:
            reason = f"credit {int(credit)} (would fail under {nc})"
        elif nd is not None and dti is not None and dti > nd:
            reason = f"DTI {dti:.0f}% (would fail under {nd}%)"
        elif nl is not None and ltv is not None and ltv > nl:
            reason = f"LTV {ltv:.0f}% (would fail under {nl}%)"
        if reason:
            count += 1
            if len(examples) < 5:
                examples.append({"application_id": r["application_id"], "name": r["full_name"] or r["application_id"], "reason": reason})
    return {"count": count, "examples": examples}


# ── Loan rules-note: does this loan run under an older pinned version? ──
@router.get("/loan-note")
async def loan_note(application_id: str, tenant_id: str = Depends(get_tenant_id)) -> dict:
    _require_db()
    pool = await _get_pool()
    async with pool.acquire() as conn:
        es = await conn.fetchrow(
            "SELECT pinned_rule_version, application_date FROM entity_states WHERE application_id=$1 AND tenant_id=$2",
            application_id, tenant_id)
        if es is None or es["pinned_rule_version"] is None:
            return {"show": False}
        pinned = await conn.fetchrow("SELECT * FROM tenant_rules WHERE rule_version_id=$1", es["pinned_rule_version"])
        current = await _active_version(conn, tenant_id)
    if pinned is None or current is None or pinned["version"] == current["version"]:
        return {"show": False}
    pr, cr = _jsonb(pinned["rules"]), _jsonb(current["rules"])
    diffs = []
    for label, a, b in (("DTI max", "dti", "back_max"), ("Credit floor", "credit", "min_score"), ("LTV max", "ltv", "max")):
        pv, cv = (pr.get(a) or {}).get(b), (cr.get(a) or {}).get(b)
        if pv != cv:
            diffs.append({"field": label, "pinned": pv, "current": cv})
    return {
        "show": True, "application_date": _iso(es["application_date"]),
        "applied_version": pinned["version"], "applied_effective": _iso(pinned["effective_from"]),
        "current_version": current["version"], "current_effective": _iso(current["effective_from"]),
        "differences": diffs,
    }


# ── 0. Pipeline-impact preview for a proposed rule set ──────────────
@router.post("/impact")
async def impact(payload: dict = Body(...), tenant_id: str = Depends(get_tenant_id)) -> dict:
    _require_db()
    rules = payload.get("rules") or {}
    pool = await _get_pool()
    async with pool.acquire() as conn:
        return await _pipeline_impact(conn, tenant_id, rules)


# ── 1. Rollback to a prior version ──────────────────────────────────
class RollbackBody(BaseModel):
    rollback_to_version: int
    reason: str


@router.post("/rollback")
async def rollback(body: RollbackBody, user: dict = Depends(get_current_user)) -> dict:
    _require(user, "admin", "manager")
    _require_db()
    tid = user["tenant_id"]
    if not body.reason.strip():
        raise HTTPException(422, "A reason for the rollback is required")
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await _check_not_frozen(conn, tid)
        src = await conn.fetchrow("SELECT * FROM tenant_rules WHERE tenant_id=$1 AND version=$2", tid, body.rollback_to_version)
        if src is None:
            raise HTTPException(404, f"Version {body.rollback_to_version} not found")
        active = await _active_version(conn, tid)
        cur_v = active["version"] if active else None
        new_v = await _next_version(conn, tid)
        await conn.execute("DELETE FROM tenant_rules WHERE tenant_id=$1 AND status='pending_approval'", tid)
        await conn.execute(
            "INSERT INTO tenant_rules (tenant_id, version, status, rules, programs, changes_summary, change_reason, "
            " created_by, change_type, rolled_back_from) "
            "VALUES ($1,$2,'pending_approval',$3::jsonb,$4::jsonb,$5,$6,$7,'rollback',$8)",
            tid, new_v, json.dumps(_jsonb(src["rules"])), json.dumps(_jsonb(src["programs"])),
            f"Rollback to v{body.rollback_to_version} rules", body.reason.strip(), _uuid(user.get("user_id")), cur_v)
        impact = await _pipeline_impact(conn, tid, _jsonb(src["rules"]))
    return {
        "version": new_v, "status": "pending_approval", "rolled_back_from": cur_v,
        "restores_version": body.rollback_to_version,
        "message": f"v{new_v} created as rollback from v{cur_v}. Restoring v{body.rollback_to_version} rules.",
        "affected_pipeline_loans": impact["count"], "examples": impact["examples"],
    }


# ── 2. Schedule a future rule version ───────────────────────────────
class ScheduleBody(BaseModel):
    rules: dict
    scheduled_for: str
    reason: str
    programs: Optional[list[str]] = None


@router.post("/schedule")
async def schedule(body: ScheduleBody, user: dict = Depends(get_current_user)) -> dict:
    _require(user, "admin", "manager")
    _require_db()
    tid = user["tenant_id"]
    try:
        when = datetime.fromisoformat(body.scheduled_for.replace("Z", "+00:00"))
        if when.tzinfo is not None:
            when = when.astimezone(timezone.utc).replace(tzinfo=None)
    except ValueError:
        raise HTTPException(422, "scheduled_for must be ISO-8601")
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await _check_not_frozen(conn, tid)
        active = await _active_version(conn, tid)
        programs = body.programs or (_jsonb(active["programs"]) if active else ["conventional", "fha"])
        errs, _ = validate_overlay(body.rules, programs)
        if errs:
            raise HTTPException(400, errs[0])
        new_v = await _next_version(conn, tid)
        await conn.execute(
            "INSERT INTO tenant_rules (tenant_id, version, status, rules, programs, changes_summary, change_reason, "
            " created_by, approved_by, approved_at, change_type, scheduled_for) "
            "VALUES ($1,$2,'scheduled',$3::jsonb,$4::jsonb,$5,$6,$7,$7,NOW(),'scheduled',$8)",
            tid, new_v, json.dumps(body.rules), json.dumps(programs),
            "Scheduled rule change", body.reason.strip(), _uuid(user.get("user_id")), when)
    return {"version": new_v, "status": "scheduled", "activates": when.date().isoformat()}


# ── 3. Shadow mode (dual evaluation) ────────────────────────────────
class ShadowBody(BaseModel):
    rules: dict
    shadow_duration_days: int = 14
    reason: str
    programs: Optional[list[str]] = None


@router.post("/shadow")
async def shadow(body: ShadowBody, user: dict = Depends(get_current_user)) -> dict:
    _require(user, "admin", "manager")
    _require_db()
    tid = user["tenant_id"]
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await _check_not_frozen(conn, tid)
        active = await _active_version(conn, tid)
        if active is None:
            raise HTTPException(400, "No active version to shadow against")
        active_rules = _jsonb(active["rules"])
        programs = body.programs or _jsonb(active["programs"])
        # one shadow at a time
        await conn.execute("UPDATE tenant_rules SET status='superseded' WHERE tenant_id=$1 AND status='shadow'", tid)
        new_v = await _next_version(conn, tid)
        await conn.execute(
            "INSERT INTO tenant_rules (tenant_id, version, status, rules, programs, changes_summary, change_reason, "
            " created_by, change_type, shadow_duration_days, expires_at) "
            "VALUES ($1,$2,'shadow',$3::jsonb,$4::jsonb,$5,$6,$7,'shadow',$8,$9)",
            tid, new_v, json.dumps(body.rules), json.dumps(programs),
            "Shadow-mode test", body.reason.strip(), _uuid(user.get("user_id")), body.shadow_duration_days,
            datetime.utcnow() + timedelta(days=body.shadow_duration_days))
        # dual-evaluate the active book and log differences
        rows = await _active_loans(conn, tid)
        await conn.execute("DELETE FROM shadow_evaluations WHERE tenant_id=$1 AND shadow_version=$2", tid, new_v)
        diffs = 0
        for r in rows:
            ar = _evaluate(active_rules, r["mid_credit_score"], r["dti_back"], r["ltv"])
            sr = _evaluate(body.rules, r["mid_credit_score"], r["dti_back"], r["ltv"])
            diff = None if ar == sr else f"Would change from {ar.upper()} to {sr.upper()}"
            if diff:
                diffs += 1
            await conn.execute(
                "INSERT INTO shadow_evaluations (application_id, tenant_id, active_version, shadow_version, "
                " active_result, shadow_result, difference) VALUES ($1,$2,$3,$4,$5,$6,$7)",
                r["application_id"], tid, active["version"], new_v, ar, sr, diff)
    return {"shadow_version": new_v, "status": "shadow", "duration_days": body.shadow_duration_days,
            "loans_evaluated": len(rows), "differences": diffs}


@router.get("/shadow-report")
async def shadow_report(tenant_id: str = Depends(get_tenant_id)) -> dict:
    _require_db()
    pool = await _get_pool()
    async with pool.acquire() as conn:
        sh = await conn.fetchrow("SELECT * FROM tenant_rules WHERE tenant_id=$1 AND status='shadow' ORDER BY version DESC LIMIT 1", tenant_id)
        if sh is None:
            return {"active": False, "message": "No shadow test is running."}
        evals = await conn.fetch(
            """SELECT se.*, ap.full_name FROM shadow_evaluations se
               LEFT JOIN applications a ON a.application_id = se.application_id
               LEFT JOIN applicants ap ON ap.applicant_id = a.applicant_id
               WHERE se.tenant_id=$1 AND se.shadow_version=$2""",
            tenant_id, sh["version"])
    active_appr = sum(1 for e in evals if e["active_result"] == "allow")
    shadow_appr = sum(1 for e in evals if e["shadow_result"] == "allow")
    affected = [{"application_id": e["application_id"], "name": e["full_name"] or e["application_id"], "difference": e["difference"]}
                for e in evals if e["difference"]]
    started = sh["created_at"]
    day = (datetime.utcnow() - started).days + 1 if started else 1
    return {
        "active": True, "shadow_version": sh["version"], "duration_days": sh["shadow_duration_days"],
        "day": min(day, sh["shadow_duration_days"] or day), "loans_evaluated": len(evals),
        "active_approved": active_appr, "active_denied": len(evals) - active_appr,
        "shadow_approved": shadow_appr, "shadow_denied": len(evals) - shadow_appr,
        "additional_denials": max(0, active_appr - shadow_appr), "affected_loans": affected,
        "changes_summary": sh["changes_summary"],
    }


# ── 5. Emergency change (immediate, bypasses approval) ──────────────
class EmergencyBody(BaseModel):
    rules: dict
    reason: str
    emergency_type: str = "market_event"
    programs: Optional[list[str]] = None


@router.post("/emergency")
async def emergency(body: EmergencyBody, user: dict = Depends(get_current_user)) -> dict:
    _require(user, "admin", "manager")  # manager minimum
    _require_db()
    tid = user["tenant_id"]
    if not body.reason.strip():
        raise HTTPException(422, "An emergency reason is required")
    pool = await _get_pool()
    async with pool.acquire() as conn:
        active = await _active_version(conn, tid)
        programs = body.programs or (_jsonb(active["programs"]) if active else ["conventional", "fha"])
        now = datetime.utcnow()
        new_v = await _next_version(conn, tid)
        if active:
            await conn.execute("UPDATE tenant_rules SET status='superseded', effective_to=$1 WHERE rule_version_id=$2", now, active["rule_version_id"])
        await conn.execute(
            "INSERT INTO tenant_rules (tenant_id, version, status, rules, programs, changes_summary, change_reason, "
            " created_by, change_type, emergency_type, effective_from) "
            "VALUES ($1,$2,'active',$3::jsonb,$4::jsonb,$5,$6,$7,'emergency',$8,$9)",
            tid, new_v, json.dumps(body.rules), json.dumps(programs),
            "Emergency rule change", body.reason.strip(), _uuid(user.get("user_id")), body.emergency_type, now)
        # log a rescreen of affected pipeline loans
        impact = await _pipeline_impact(conn, tid, body.rules)
        await conn.execute(
            "INSERT INTO rescreen_events (tenant_id, reason, source, triggered_by, loans_rescreened) VALUES ($1,$2,'emergency',$3,$4)",
            tid, body.reason.strip()[:200], _uuid(user.get("user_id")), impact["count"])
    deadline = now + timedelta(hours=24)
    return {
        "version": new_v, "status": "active", "change_type": "emergency", "emergency_type": body.emergency_type,
        "ratification_deadline": deadline.isoformat() + "Z", "changed_by": user.get("email"),
        "affected_pipeline_loans": impact["count"],
        "message": "Emergency change active immediately. An admin must ratify within 24 hours or it auto-reverts.",
    }


@router.post("/emergency/{version}/ratify")
async def ratify(version: int, payload: dict = Body(default={}), user: dict = Depends(get_current_user)) -> dict:
    _require(user, "admin")
    _require_db()
    tid = user["tenant_id"]
    ratified = bool(payload.get("ratified", True))
    pool = await _get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT * FROM tenant_rules WHERE tenant_id=$1 AND version=$2 AND change_type='emergency'", tid, version)
            if row is None:
                raise HTTPException(404, "Emergency version not found")
            if ratified:
                await conn.execute("UPDATE tenant_rules SET ratified_by=$1, ratified_at=NOW() WHERE rule_version_id=$2",
                                   _uuid(user.get("user_id")), row["rule_version_id"])
                return {"ok": True, "ratified": True, "version": version}
            # revert: supersede emergency, reactivate the prior version
            now = datetime.utcnow()
            await conn.execute("UPDATE tenant_rules SET status='superseded', effective_to=$1 WHERE rule_version_id=$2", now, row["rule_version_id"])
            prev = await conn.fetchrow(
                "SELECT * FROM tenant_rules WHERE tenant_id=$1 AND status='superseded' AND version < $2 ORDER BY version DESC LIMIT 1", tid, version)
            if prev:
                await conn.execute("UPDATE tenant_rules SET status='active', effective_to=NULL WHERE rule_version_id=$1", prev["rule_version_id"])
    return {"ok": True, "ratified": False, "reverted_to": prev["version"] if prev else None,
            "reason": payload.get("reason")}


# ── 7. Examination mode (freeze) ────────────────────────────────────
@router.post("/examination-mode")
async def examination_mode(payload: dict = Body(...), user: dict = Depends(get_current_user)) -> dict:
    _require(user, "admin")
    _require_db()
    tid = user["tenant_id"]
    action = (payload.get("action") or "").strip()
    pool = await _get_pool()
    async with pool.acquire() as conn:
        if action == "start":
            existing = await _examination(conn, tid)
            if existing:
                return {"active": True, "examiner": existing["examiner"], "message": "Examination already active."}
            await conn.execute(
                "INSERT INTO examination_periods (tenant_id, examiner, reason, started_by) VALUES ($1,$2,$3,$4)",
                tid, payload.get("examiner") or "Examiner", payload.get("reason"), _uuid(user.get("user_id")))
            return {"active": True, "examiner": payload.get("examiner"), "message": "Examination mode active — rule changes frozen."}
        if action == "end":
            await conn.execute(
                "UPDATE examination_periods SET is_active=false, ended_at=NOW(), ended_by=$1 WHERE tenant_id=$2 AND is_active=true",
                _uuid(user.get("user_id")), tid)
            return {"active": False, "message": "Examination mode ended — rule changes restored."}
    raise HTTPException(422, "action must be 'start' or 'end'")


# ── 8. Retrospective analysis ───────────────────────────────────────
class RetroBody(BaseModel):
    date_range_start: str
    date_range_end: str
    simulate_version: int


@router.post("/retrospective")
async def retrospective(body: RetroBody, user: dict = Depends(get_current_user)) -> dict:
    _require(user, "admin", "manager")
    _require_db()
    tid = user["tenant_id"]
    pool = await _get_pool()
    async with pool.acquire() as conn:
        sim = await conn.fetchrow("SELECT * FROM tenant_rules WHERE tenant_id=$1 AND version=$2", tid, body.simulate_version)
        if sim is None:
            raise HTTPException(404, f"Version {body.simulate_version} not found")
        sim_rules = _jsonb(sim["rules"])
        active = await _active_version(conn, tid)
        orig_rules = _jsonb(active["rules"]) if active else sim_rules
        # The "originated" book for the window (use the tenant's loans as the sample).
        rows = await conn.fetch(
            """SELECT es.application_id, es.dti_back, es.mid_credit_score, es.ltv, es.loan_status
               FROM entity_states es WHERE es.tenant_id=$1""", tid)
        orig_appr = sim_appr = 0
        extra_denials: list[str] = []
        for r in rows:
            o = _evaluate(orig_rules, r["mid_credit_score"], r["dti_back"], r["ltv"])
            s = _evaluate(sim_rules, r["mid_credit_score"], r["dti_back"], r["ltv"])
            orig_appr += o == "allow"
            sim_appr += s == "allow"
            if o == "allow" and s == "block":
                extra_denials.append(r["application_id"])
        total = len(rows)
        addl = max(0, orig_appr - sim_appr)
        # "performing" split: active/funded loans are performing; halted ≈ delinquent.
        delinq = sum(1 for r in rows if r["application_id"] in extra_denials and r["loan_status"] == "halted")
        performing = len(extra_denials) - delinq
        await conn.execute(
            "INSERT INTO retrospective_analyses (tenant_id, date_range_start, date_range_end, original_version, "
            " simulated_version, total_loans, original_approved, original_denied, simulated_approved, simulated_denied, run_by) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)",
            tid, _date(body.date_range_start), _date(body.date_range_end), active["version"] if active else None, body.simulate_version,
            total, orig_appr, total - orig_appr, sim_appr, total - sim_appr, _uuid(user.get("user_id")))
    return {
        "total_loans": total,
        "original": {"approved": orig_appr, "denied": total - orig_appr},
        "simulated": {"approved": sim_appr, "denied": total - sim_appr},
        "additional_denials": addl, "additional_approvals": max(0, sim_appr - orig_appr),
        "affected_loans": extra_denials[:50],
        "performing_analysis": {
            "of_additional_denials": {"currently_performing": performing, "currently_delinquent": delinq},
            "conclusion": f"Tighter rules would have prevented {delinq} problem loan(s) but also denied {performing} performing loan(s).",
        },
    }


# ── 9. Reconstruct the decision environment at a moment ─────────────
@router.get("/reconstruct")
async def reconstruct(date: str, application_id: str, tenant_id: str = Depends(get_tenant_id)) -> dict:
    _require_db()
    try:
        ts = datetime.fromisoformat(date.replace("Z", "+00:00"))
        if ts.tzinfo is not None:
            ts = ts.astimezone(timezone.utc).replace(tzinfo=None)
    except ValueError:
        raise HTTPException(422, "date must be ISO-8601")
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rules_row = await conn.fetchrow(
            "SELECT * FROM tenant_rules WHERE tenant_id=$1 AND status IN ('active','superseded') "
            "AND effective_from <= $2 AND (effective_to IS NULL OR effective_to > $2) ORDER BY version DESC LIMIT 1",
            tenant_id, ts)
        es = await conn.fetchrow("SELECT * FROM entity_states WHERE application_id=$1 AND tenant_id=$2", application_id, tenant_id)
        decs = await conn.fetch(
            "SELECT decision_id, outcome, confidence, decided_at, human_action, human_reviewer, acted_at "
            "FROM decision_outputs WHERE application_id=$1 AND decided_at <= $2 ORDER BY decided_at", application_id, ts)
        ofac = await conn.fetchrow("SELECT last_success, record_count FROM data_source_status WHERE source_id='ofac_sdn'")
        names = await _user_names(conn, tenant_id)
        ap = await conn.fetchrow(
            "SELECT ap.full_name FROM applications a LEFT JOIN applicants ap ON ap.applicant_id=a.applicant_id WHERE a.application_id=$1",
            application_id)
    if es is None:
        raise HTTPException(404, f"Unknown application {application_id}")
    rules = _jsonb(rules_row["rules"]) if rules_row else {}
    human = next((d for d in decs if d["human_action"]), None)
    return {
        "timestamp": date, "application_id": application_id,
        "rules_active": {
            "version": rules_row["version"] if rules_row else None,
            "effective_from": _iso(rules_row["effective_from"]) if rules_row else None,
            "dti_max": (rules.get("dti") or {}).get("back_max"),
            "credit_floor": (rules.get("credit") or {}).get("min_score"),
            "ltv_max": (rules.get("ltv") or {}).get("max"),
        },
        "ofac_version": _iso(ofac["last_success"]) if ofac else None,
        "ofac_entries": ofac["record_count"] if ofac else None,
        "agency_guidelines_version": "2026.02",
        "conforming_limit": "$766,550 (2026)",
        "entity_state_at_time": {
            "credit_score": _norm(es["mid_credit_score"]), "dti": _norm(es["dti_back"], True),
            "ltv": _norm(es["ltv"], True), "loan_status": es["loan_status"], "borrower": ap["full_name"] if ap else None,
        },
        "ai_evaluation": [{
            "decision_id": d["decision_id"], "outcome": d["outcome"], "confidence": d["confidence"],
            "at": _iso(d["decided_at"]),
        } for d in decs],
        "human_action": {
            "by": human["human_reviewer"], "action": human["human_action"], "at": _iso(human["acted_at"]),
        } if human else None,
    }


# ── 10. Pipeline policy for the active version ──────────────────────
@router.put("/pipeline-policy")
async def pipeline_policy(payload: dict = Body(...), user: dict = Depends(get_current_user)) -> dict:
    _require(user, "admin", "manager")
    _require_db()
    tid = user["tenant_id"]
    policy = (payload.get("policy") or "").strip()
    if policy not in ("grandfather", "immediate", "cutoff_date"):
        raise HTTPException(422, "policy must be grandfather|immediate|cutoff_date")
    cutoff = payload.get("cutoff_date")
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await _check_not_frozen(conn, tid)
        active = await _active_version(conn, tid)
        if active is None:
            raise HTTPException(404, "No active version")
        await conn.execute(
            "UPDATE tenant_rules SET pipeline_policy=$1, pipeline_cutoff_date=$2 WHERE rule_version_id=$3",
            policy, date.fromisoformat(cutoff) if (policy == "cutoff_date" and cutoff) else None, active["rule_version_id"])
    return {"ok": True, "policy": policy, "cutoff_date": cutoff if policy == "cutoff_date" else None}


# ── Regulation transparency — all 4 layers visible to admin/compliance ──
@router.get("/regulations/transparency")
async def regulation_transparency(
    layer: Optional[str] = None,
    state_code: Optional[str] = None,
    category: Optional[str] = None,
    user: dict = Depends(get_current_user),
) -> dict:
    """Federal + agency + state + lender rules in one payload, each with a
    last_refreshed timestamp, plus the pipeline-protection summary (PROMPT B).
    Restricted to admin / compliance."""
    _require(user, "admin", "compliance", "super_admin")
    _require_db()
    tenant_id = user.get("tenant_id", "default")

    def _row(r) -> dict:
        return {
            "layer": r["layer"], "state_code": r["state_code"], "source": r["source"],
            "rule_name": r["rule_name"], "display_value": r["display_value"],
            "description": r["description"], "citation": r["citation"],
            "effective_date": _iso(r["effective_date"]), "last_refreshed": _iso(r["last_refreshed"]),
            "verified_by": r["verified_by"], "is_active": r["is_active"],
            "category": r["category"], "regulation_id": r["regulation_id"],
        }

    pool = await _get_pool()
    async with pool.acquire() as conn:
        where = ["1=1"]
        params: list = []
        if layer and layer != "lender":
            params.append(layer)
            where.append(f"layer = ${len(params)}")
        if state_code:
            params.append(state_code.upper())
            where.append(f"state_code = ${len(params)}")
        if category:
            params.append(category)
            where.append(f"category = ${len(params)}")
        rows = await conn.fetch(
            f"""
            SELECT layer, state_code, source, rule_name, display_value, description,
                   citation, effective_date, last_refreshed, verified_by, is_active,
                   category, regulation_id
            FROM vw_regulation_transparency
            WHERE {' AND '.join(where)}
            ORDER BY layer, source, rule_name
            """,
            *params,
        )

        lender_rows = []
        if not layer or layer == "lender":
            lender_rows = await conn.fetch(
                """
                SELECT rule_version_id::text AS rule_version_id, version, status, rules,
                       changes_summary, change_reason, effective_from, approved_at,
                       pipeline_cutoff_date, change_type, scheduled_for
                FROM tenant_rules WHERE tenant_id = $1 ORDER BY version DESC
                """,
                tenant_id,
            )

        protection = await conn.fetchrow(
            """
            SELECT COUNT(*) FILTER (WHERE rate_locked) AS total_locked,
                   COUNT(*) FILTER (WHERE rate_locked AND pinned_rule_version IS NOT NULL) AS pinned,
                   COUNT(*) FILTER (WHERE rate_locked AND pinned_rule_version IS NULL) AS unpinned
            FROM entity_states WHERE tenant_id = $1
            """,
            tenant_id,
        )
        current = await _active_version(conn, tenant_id)

    federal = [_row(r) for r in rows if r["layer"] == "federal"]
    agency = [_row(r) for r in rows if r["layer"] == "agency"]
    state = [_row(r) for r in rows if r["layer"] == "state"]
    lender = [
        {
            "rule_version_id": r["rule_version_id"], "version": r["version"], "status": r["status"],
            "rules": _jsonb(r["rules"]), "changes_summary": r["changes_summary"],
            "change_reason": r["change_reason"], "effective_from": _iso(r["effective_from"]),
            "approved_at": _iso(r["approved_at"]), "pipeline_cutoff_date": _iso(r["pipeline_cutoff_date"]),
            "change_type": r["change_type"], "scheduled_for": _iso(r["scheduled_for"]),
        }
        for r in lender_rows
    ]

    def _maxref(layer_name: str):
        vals = [r["last_refreshed"] for r in rows if r["layer"] == layer_name and r["last_refreshed"]]
        return _iso(max(vals)) if vals else None

    unpinned = protection["unpinned"] if protection else 0
    return {
        "layers": {"federal": federal, "agency": agency, "state": state, "lender": lender},
        "summary": {
            "federal_count": len(federal),
            "agency_count": len(agency),
            "state_count": len(state),
            "lender_versions": len(lender),
            "states_covered": sorted({r["state_code"] for r in rows if r["layer"] == "state" and r["state_code"]}),
            "last_federal_refresh": _maxref("federal"),
            "last_agency_refresh": _maxref("agency"),
        },
        "pipeline_protection": {
            "total_locked": protection["total_locked"] if protection else 0,
            "pinned": protection["pinned"] if protection else 0,
            "unpinned": unpinned,
            "current_version": current["version"] if current else None,
            "current_effective": _iso(current["effective_from"]) if current else None,
            "note": (
                "All locked loans are pinned to their rule version at lock date."
                if unpinned == 0
                else f"{unpinned} locked loans have no pin (tenant may have no rule history)."
            ),
        },
    }


# ════════════════════════════════════════════════════════════════════
# PROMPT E — Policy Studio backend additions
# ════════════════════════════════════════════════════════════════════

# ── Part 1. Floor-enforced overlay update (force/warnings contract) ──
class OverlayUpdate(BaseModel):
    rules: dict
    change_reason: str
    changes_summary: Optional[str] = None
    programs: Optional[list[str]] = None
    force: bool = False


@router.put("/overlay")
async def update_overlay(body: OverlayUpdate, user: dict = Depends(get_current_user)) -> dict:
    """Floor-enforced overlay change. Hard floors (credit < 580 FHA, DTI > 57,
    LTV > 97) return 422. Soft warnings (credit < 620, DTI > 43) require
    ``force=true`` to proceed; otherwise the warnings are returned uncommitted.
    On success a pending_approval version is created (same as the classic PUT)."""
    _require(user, "admin", "manager")
    _require_db()
    tenant_id = user["tenant_id"]
    if not (body.change_reason or "").strip():
        raise HTTPException(422, "A reason for the change is required")
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await _check_not_frozen(conn, tenant_id)
        active = await _active_version(conn, tenant_id)
        programs = body.programs or (_jsonb(active["programs"]) if active else ["conventional", "fha"])
        errors, warnings = validate_overlay(body.rules, programs)
        if errors:
            raise HTTPException(status_code=422, detail=errors[0])
        if warnings and not body.force:
            return {"ok": False, "requires_confirmation": True, "warnings": warnings, "errors": []}

        # Boundary validation suite — a bad rule can never go live.
        from api.accord.validation import run_validation
        val = await run_validation(tenant_id, proposed_rules=body.rules, programs=programs)
        if val["failed"] > 0:
            fails = [t for t in val["tests"] if not t["passed"]][:3]
            detail = "; ".join(f"{t['id']}: expected {t['expected']} but got {t['actual']}" for t in fails)
            raise HTTPException(422, f"Rule change cannot be activated — {val['failed']} validation test(s) failed: {detail}")

        next_version = (await conn.fetchval(
            "SELECT COALESCE(MAX(version), 0) + 1 FROM tenant_rules WHERE tenant_id=$1", tenant_id)) or 1
        await conn.execute(
            "DELETE FROM tenant_rules WHERE tenant_id=$1 AND status='pending_approval'", tenant_id)
        new_id = await conn.fetchval(
            "INSERT INTO tenant_rules (tenant_id, version, status, rules, programs, changes_summary, change_reason, created_by) "
            "VALUES ($1,$2,'pending_approval',$3::jsonb,$4::jsonb,$5,$6,$7) RETURNING rule_version_id",
            tenant_id, next_version, json.dumps(body.rules), json.dumps(programs),
            body.changes_summary, body.change_reason, _uuid(user.get("user_id")))
    return {"ok": True, "rule_version_id": str(new_id), "version": next_version,
            "status": "pending_approval", "warnings": warnings}


# ── Part 2. Shadow impact preview — proposed rules vs active decisions ──
# (decision_id, overlay category, overlay field, entity_states column, direction, is_pct)
_PREVIEW_DECISIONS = [
    ("credit_assessment", "credit", "min_score", "mid_credit_score", "below", False),
    ("dti_calculation", "dti", "back_max", "dti_back", "above", True),
    ("ltv_assessment", "ltv", "max", "ltv", "above", True),
]


async def _preview_impact(conn, tenant_id: str, proposed: dict) -> dict:
    loans = await _active_loans(conn, tenant_id)
    dids = [d[0] for d in _PREVIEW_DECISIONS]
    outc = await conn.fetch(
        "SELECT DISTINCT ON (application_id, decision_id) application_id, decision_id, outcome "
        "FROM decision_outputs WHERE tenant_id=$1 AND decision_id = ANY($2) "
        "ORDER BY application_id, decision_id, version DESC",
        tenant_id, dids)
    cur = {(r["application_id"], r["decision_id"]): r["outcome"] for r in outc}

    by_decision: list = []
    affected: set = set()
    for did, cat, field, valcol, direction, pct in _PREVIEW_DECISIONS:
        thr = (proposed.get(cat) or {}).get(field)
        if not isinstance(thr, (int, float)):
            continue
        newly_blocked: list = []
        newly_allowed: list = []
        for l in loans:
            v = _norm(l[valcol], pct)
            if v is None:
                continue
            proposed_block = (v < thr) if direction == "below" else (v > thr)
            was_block = cur.get((l["application_id"], did)) == "block"
            if proposed_block and not was_block:
                newly_blocked.append(l)
                affected.add(l["application_id"])
            elif not proposed_block and was_block:
                newly_allowed.append(l)
                affected.add(l["application_id"])
        if newly_blocked or newly_allowed:
            def _samp(rows, change):
                return [{"application_id": x["application_id"], "name": x["full_name"] or x["application_id"],
                         "value": round(_norm(x[valcol], pct), 1), "change": change} for x in rows[:5]]
            by_decision.append({
                "decision_id": did, "threshold": thr,
                "newly_blocked": len(newly_blocked), "newly_allowed": len(newly_allowed),
                "samples": (_samp(newly_blocked, "newly blocked") + _samp(newly_allowed, "newly allowed"))[:5],
            })

    total = len(affected)
    nbt = sum(d["newly_blocked"] for d in by_decision)
    nat = sum(d["newly_allowed"] for d in by_decision)
    if total == 0:
        rec = "No active pipeline loans are affected by this change."
    else:
        rec = (f"{total} active loan(s) affected — {nbt} newly blocked, {nat} newly allowed. "
               "Review the sample loans before submitting for approval.")
    return {"total_loans_affected": total, "active_loans_evaluated": len(loans),
            "impact_by_decision": by_decision, "recommendation": rec}


@router.post("/overlay/preview-impact")
async def preview_impact(payload: dict = Body(...), tenant_id: str = Depends(get_tenant_id)) -> dict:
    _require_db()
    rules = payload.get("rules") or {}
    pool = await _get_pool()
    async with pool.acquire() as conn:
        return await _preview_impact(conn, tenant_id, rules)


# ── Part 3. Rate sheet upload (CSV -> rate_sheet_entry) ──
_RATE_SHEET_COLS = ("product_id", "credit_band", "ltv_max", "base_rate", "llpa_adjustment", "effective_date")


@router.post("/rate-sheet/upload")
async def rate_sheet_upload(file: UploadFile = File(...), user: dict = Depends(get_current_user)) -> dict:
    _require(user, "admin", "manager")
    _require_db()
    tid = user["tenant_id"]
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1", errors="replace")
    if not text.strip():
        raise HTTPException(400, "Uploaded file is empty")

    reader = csv.DictReader(io.StringIO(text))
    cols = {(h or "").strip() for h in (reader.fieldnames or [])}
    missing = [c for c in _RATE_SHEET_COLS if c not in cols]
    if missing:
        raise HTTPException(422, f"CSV missing required columns: {', '.join(missing)}")

    rows: list = []
    errors: list = []
    for i, r in enumerate(reader, start=2):
        try:
            rows.append({
                "product_id": (r["product_id"] or "").strip(),
                "credit_band": (r["credit_band"] or "").strip(),
                "ltv_max": float(r["ltv_max"]),
                "base_rate": float(r["base_rate"]),
                "llpa_adjustment": float((r["llpa_adjustment"] or "0")),
                "effective_date": date.fromisoformat((r["effective_date"] or "").strip()[:10]),
            })
        except (ValueError, TypeError, KeyError) as e:
            errors.append(f"Row {i}: {e}")
            if len(errors) > 50:
                break
    if not rows:
        raise HTTPException(422, "No valid rows parsed" + (f" - {errors[0]}" if errors else ""))

    pool = await _get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            uploaded = 0
            for row in rows:
                await conn.execute(
                    "INSERT INTO rate_sheet_entry "
                    "(tenant_id, product_id, credit_band, ltv_max, base_rate, llpa_adjustment, effective_date, uploaded_by, uploaded_at) "
                    "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,NOW()) "
                    "ON CONFLICT (tenant_id, product_id, credit_band, ltv_max, effective_date) "
                    "DO UPDATE SET base_rate=EXCLUDED.base_rate, llpa_adjustment=EXCLUDED.llpa_adjustment, "
                    "uploaded_by=EXCLUDED.uploaded_by, uploaded_at=NOW()",
                    tid, row["product_id"], row["credit_band"], row["ltv_max"], row["base_rate"],
                    row["llpa_adjustment"], row["effective_date"], _uuid(user.get("user_id")))
                uploaded += 1
            # Best-effort freshness logging — never fail the upload over this.
            try:
                await conn.execute(
                    "INSERT INTO data_source_status (source_id, source_name, last_download, last_success, record_count, status, updated_at) "
                    "VALUES ('rate_sheet','Rate Sheet Upload',NOW(),NOW(),$1,'ok',NOW()) "
                    "ON CONFLICT (source_id) DO UPDATE SET last_download=NOW(), last_success=NOW(), "
                    "record_count=$1, status='ok', error_message=NULL, updated_at=NOW()",
                    uploaded)
            except Exception:
                pass
    eff = sorted({r["effective_date"].isoformat() for r in rows})
    return {"uploaded": uploaded, "rows_in_file": uploaded + len(errors), "errors": errors[:10],
            "effective_dates": eff, "uploaded_at": datetime.utcnow().isoformat() + "Z"}


@router.get("/rate-sheet/status")
async def rate_sheet_status(tenant_id: str = Depends(get_tenant_id)) -> dict:
    _require_db()
    pool = await _get_pool()
    async with pool.acquire() as conn:
        ds = await conn.fetchrow("SELECT last_success, record_count, status FROM data_source_status WHERE source_id='rate_sheet'")
        total = await conn.fetchval("SELECT COUNT(*) FROM rate_sheet_entry WHERE tenant_id=$1", tenant_id)
        # Full current rate table (joined to the uploader for the "by …" line).
        recent = await conn.fetch(
            "SELECT rse.product_id, rse.credit_band, rse.ltv_max, rse.base_rate, rse.llpa_adjustment, "
            "       rse.effective_date, rse.uploaded_at, u.name AS uploaded_by_name, u.email AS uploaded_by_email "
            "FROM rate_sheet_entry rse "
            "LEFT JOIN users u ON u.user_id = rse.uploaded_by "
            "WHERE rse.tenant_id=$1 "
            "ORDER BY rse.product_id, rse.credit_band, rse.ltv_max LIMIT 500", tenant_id)
        # Most recent upload for THIS tenant — drives the "Last uploaded … by …" header.
        last = await conn.fetchrow(
            "SELECT rse.uploaded_at, u.name AS uploaded_by_name, u.email AS uploaded_by_email "
            "FROM rate_sheet_entry rse LEFT JOIN users u ON u.user_id = rse.uploaded_by "
            "WHERE rse.tenant_id=$1 ORDER BY rse.uploaded_at DESC LIMIT 1", tenant_id)

    def _uploader(row) -> "str | None":
        return (row["uploaded_by_name"] or row["uploaded_by_email"]) if row else None

    return {
        # Prefer the tenant's own latest entry; fall back to the global source log.
        "last_upload": _iso(last["uploaded_at"]) if last else (_iso(ds["last_success"]) if ds else None),
        "last_uploaded_by": _uploader(last),
        "last_record_count": ds["record_count"] if ds else None,
        "total_entries": total,
        "recent": [{
            "product_id": r["product_id"], "credit_band": r["credit_band"], "ltv_max": float(r["ltv_max"]),
            "base_rate": float(r["base_rate"]), "llpa_adjustment": float(r["llpa_adjustment"]),
            "effective_date": _iso(r["effective_date"]), "uploaded_at": _iso(r["uploaded_at"]),
            "uploaded_by": _uploader(r),
        } for r in recent],
    }


# ── Pipeline protection summary (Section 5 of Policy Studio) ──
@router.get("/pipeline-protection")
async def pipeline_protection(tenant_id: str = Depends(get_tenant_id)) -> dict:
    """Rate-lock / pipeline-protection stats for the tenant: how many loans are
    rate-locked, how many are pinned to a rule version, and which older versions
    are still protecting loans even though a newer version is active."""
    _require_db()
    pool = await _get_pool()
    async with pool.acquire() as conn:
        has_history = bool(await conn.fetchval(
            "SELECT 1 FROM tenant_rules WHERE tenant_id=$1 LIMIT 1", tenant_id))
        agg = await conn.fetchrow(
            """SELECT COUNT(*) FILTER (WHERE rate_locked) AS total_locked,
                      COUNT(*) FILTER (WHERE rate_locked AND pinned_rule_version IS NOT NULL) AS pinned
               FROM entity_states WHERE tenant_id=$1""",
            tenant_id)
        current = await _active_version(conn, tenant_id)
        cur_v = current["version"] if current else None
        # Loans pinned to an OLDER version than the current active one are "protected".
        protected_rows = await conn.fetch(
            """SELECT tr.version AS pinned_version, COUNT(*) AS cnt
               FROM entity_states es
               JOIN tenant_rules tr ON tr.rule_version_id = es.pinned_rule_version
               WHERE es.tenant_id=$1 AND es.rate_locked AND es.pinned_rule_version IS NOT NULL
               GROUP BY tr.version ORDER BY tr.version""",
            tenant_id)
    total_locked = agg["total_locked"] if agg else 0
    pinned = agg["pinned"] if agg else 0
    protected = [{"pinned_version": r["pinned_version"], "count": r["cnt"]}
                 for r in protected_rows if cur_v is not None and r["pinned_version"] < cur_v]
    return {
        "has_history": has_history,
        "total_locked": total_locked,
        "pinned": pinned,
        "pinned_pct": round(100 * pinned / total_locked) if total_locked else 0,
        "current_version": cur_v,
        "protected": protected,
    }


# ── Per-field pipeline impact (gap between agency baseline and your value) ──
# Agency baselines the editable overlay tightens against.
_FIELD_BASELINE = {
    "credit.min_score": ("credit", "mid_credit_score", False, 620, "above", "credit"),
    "dti.back_max":     ("dti", "dti_back", True, 50, "below", "DTI"),
    "ltv.max":          ("ltv", "ltv", True, 97, "below", "LTV"),
}


@router.get("/overlay/field-impacts")
async def field_impacts(tenant_id: str = Depends(get_tenant_id)) -> dict:
    """For each editable overlay field, how many active loans sit in the gap
    between the agency baseline and the tenant's (stricter) value — i.e. loans
    that pass the agency standard but not yours."""
    _require_db()
    pool = await _get_pool()
    async with pool.acquire() as conn:
        active = await _active_version(conn, tenant_id)
        rules = _jsonb(active["rules"]) if active else {}
        loans = await _active_loans(conn, tenant_id)

    total_active = len(loans)
    out: dict = {}
    for key, (cat, col, pct, baseline, direction, noun) in _FIELD_BASELINE.items():
        value = (rules.get(cat) or {}).get(key.split(".")[1])
        if not isinstance(value, (int, float)):
            out[key] = {"count": 0, "label": f"{total_active} active loans run under this rule."}
            continue
        n = 0
        for l in loans:
            v = _norm(l[col], pct)
            if v is None:
                continue
            # "above": your floor is higher than agency → loans in [agency, your value)
            if direction == "above":
                if baseline <= v < value:
                    n += 1
            else:  # "below": your cap is lower than agency → loans in (your value, agency]
                if value < v <= baseline:
                    n += 1
        loanword = "loan" if n == 1 else "loans"
        if direction == "above":
            if value <= baseline:
                label = f"Your floor ({int(value)}) is at the agency minimum ({baseline}) — no loans sit in the gap."
            else:
                label = f"{n} {loanword} between {noun} {baseline} and {int(value) - 1} — above the agency minimum ({baseline}), below your floor."
        else:
            if value >= baseline:
                label = f"Your cap ({int(value)}%) matches the agency max ({baseline}%) — no loans sit in the gap."
            else:
                label = f"{n} {loanword} between {noun} {int(value) + 1}% and {baseline}% — within the agency max ({baseline}%), above your cap."
        out[key] = {"count": n, "label": label}

    # Fields with no clean agency gap → just report the active population.
    for key in ("credit.prime_threshold", "dti.front_max", "ltv.no_mi_threshold",
                "fraud.watchlist_threshold", "fraud.identity_min",
                "income.max_discrepancy_pct", "reserves.primary", "reserves.investment"):
        out.setdefault(key, {"count": total_active, "label": f"{total_active} active loans run under this rule."})

    return {"impacts": out, "active_loans": total_active}


# ── PROMPT L — policy proposals (AI learns from underwriter overrides) ──
@router.get("/policy-proposals")
async def get_policy_proposals(user: dict = Depends(get_current_user)) -> dict:
    """Pending policy proposals the pattern detector raised from repeated
    underwriter overrides. Admin-only — these gate real rule changes."""
    _require(user, "admin", "super_admin")
    _require_db()
    tenant_id = user["tenant_id"]
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT proposal_id, decision_id, boundary_rule, override_count,
                      pattern_summary, proposed_change, status, created_at
               FROM policy_proposals
               WHERE tenant_id=$1 AND status='pending'
               ORDER BY override_count DESC, created_at DESC""",
            tenant_id)
    return {
        "proposals": [{
            "proposal_id": str(r["proposal_id"]), "decision_id": r["decision_id"],
            "boundary_rule": r["boundary_rule"], "override_count": r["override_count"],
            "pattern_summary": r["pattern_summary"], "proposed_change": r["proposed_change"],
            "status": r["status"], "created_at": _iso(r["created_at"]),
        } for r in rows],
        "count": len(rows),
    }


@router.post("/policy-proposals/{proposal_id}/action")
async def act_on_proposal(
    proposal_id: str, payload: dict = Body(...), user: dict = Depends(get_current_user)
) -> dict:
    """Accept or dismiss a proposal. Accept marks it accepted (the admin then
    edits the overlay in Policy Studio); dismiss removes it from the queue."""
    _require(user, "admin", "super_admin")
    _require_db()
    action = (payload or {}).get("action")
    if action not in ("accept", "dismiss"):
        raise HTTPException(422, "action must be accept or dismiss")
    tenant_id = user["tenant_id"]
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """UPDATE policy_proposals
               SET status=$1, reviewed_by=$2, reviewed_at=NOW()
               WHERE proposal_id=$3::uuid AND tenant_id=$4""",
            "accepted" if action == "accept" else "dismissed",
            user.get("email"), proposal_id, tenant_id)
    return {"status": "ok", "action": action}

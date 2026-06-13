"""Accord — Rules Dashboard API (the three-layer trust surface).

Read the regulatory / agency / customer-overlay layers, edit the overlay with
guardrails (no value may drop below a hard regulatory/agency minimum), version
+ approve changes, look up which version governed a given date, and surface data
freshness + agency change alerts. Reuses the accord asyncpg pool.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, HTTPException
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
    if isinstance(dti, (int, float)) and dti > 43:
        warnings.append(f"DTI {dti}% exceeds the QM safe-harbor limit of 43%")

    ltv = (rules.get("ltv") or {}).get("max")
    if isinstance(ltv, (int, float)) and ltv > 97:
        warnings.append(f"LTV {ltv}% exceeds the Fannie conventional maximum of 97%")

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

    errors, warnings = validate_overlay(_jsonb(active["rules"]), programs) if active else ([], [])

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
    }


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
        active = await _active_version(conn, tenant_id)
        programs = body.programs or (_jsonb(active["programs"]) if active else ["conventional", "fha"])
        errors, warnings = validate_overlay(body.rules, programs)
        if errors:
            raise HTTPException(400, errors[0])

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

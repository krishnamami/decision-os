"""Accord — Comparison Mode API.

Run Accord alongside manual underwriting for a trial period and track agreement,
building trust through evidence: where Accord agrees with the team, where it's
stricter (and caught something), and where the team's judgment differed.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel

from api.accord.auth import get_current_user, get_tenant_id
from api.accord.pipeline import _get_pool, _require_db

router = APIRouter(prefix="/api/accord/comparison", tags=["accord-comparison"])


def _iso(v: Any) -> Optional[str]:
    return v.isoformat() if hasattr(v, "isoformat") else v


# Accord outcome (allow/block/review/escalate) vs manual (approved/denied/suspended/withdrawn).
def _norm(o: str) -> str:
    o = (o or "").lower()
    return {
        "allow": "approve", "approved": "approve",
        "block": "deny", "denied": "deny", "withdrawn": "deny",
        "review": "escalate", "escalate": "escalate", "recommend": "escalate", "suspended": "escalate",
    }.get(o, o)


def classify(accord: str, manual: str) -> str:
    a, m = _norm(accord), _norm(manual)
    if a == m:
        return "agree"
    if a in ("deny", "escalate") and m == "approve":
        return "accord_stricter"
    if a == "approve" and m in ("deny", "escalate"):
        return "accord_looser"
    return "disagree"


async def _active_period(conn, tenant_id: str):
    return await conn.fetchrow(
        "SELECT * FROM comparison_periods WHERE tenant_id=$1 AND status='active' ORDER BY started_at DESC LIMIT 1", tenant_id)


async def _accord_outcome(conn, application_id: str) -> tuple[Optional[str], Optional[float]]:
    """Derive Accord's overall outcome for a loan from decision_outputs."""
    rows = await conn.fetch(
        "SELECT outcome, confidence FROM decision_outputs WHERE application_id=$1 ORDER BY decided_at DESC", application_id)
    if not rows:
        return None, None
    outcomes = [r["outcome"] for r in rows]
    conf = next((r["confidence"] for r in rows if r["confidence"] is not None), None)
    if "block" in outcomes:
        return "block", conf
    if any(o in ("escalate", "recommend") for o in outcomes):
        return "escalate", conf
    return "allow", conf


# ── 1. Start a comparison period ────────────────────────────────────
@router.post("/start")
async def start(payload: dict = Body(default={}), user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") not in ("admin", "manager"):
        raise HTTPException(403, "Admin or manager access required")
    _require_db()
    tid = user["tenant_id"]
    days = int(payload.get("duration_days", 90))
    pool = await _get_pool()
    async with pool.acquire() as conn:
        if await _active_period(conn, tid):
            raise HTTPException(400, "A comparison period is already active")
        now = datetime.utcnow()
        pid = await conn.fetchval(
            "INSERT INTO comparison_periods (tenant_id, started_at, started_by, ends_at, status) "
            "VALUES ($1,$2,$3,$4,'active') RETURNING period_id",
            tid, now, _uuid(user.get("user_id")), now + timedelta(days=days))
    return {"period_id": str(pid), "ends_at": (now + timedelta(days=days)).date().isoformat()}


# ── 2. Record the underwriter's manual decision ─────────────────────
class ManualBody(BaseModel):
    application_id: str
    manual_outcome: str  # approved, denied, suspended, withdrawn
    manual_reasoning: Optional[str] = None


@router.post("/record-manual")
async def record_manual(body: ManualBody, user: dict = Depends(get_current_user)) -> dict:
    _require_db()
    tid = user["tenant_id"]
    pool = await _get_pool()
    async with pool.acquire() as conn:
        period = await _active_period(conn, tid)
        if period is None:
            raise HTTPException(400, "No active comparison period")
        accord_outcome, accord_conf = await _accord_outcome(conn, body.application_id)
        if accord_outcome is None:
            raise HTTPException(404, "No Accord decision found for this loan yet")
        agreement = classify(accord_outcome, body.manual_outcome)
        now = datetime.utcnow()
        # one comparison row per loan — replace if re-recorded
        await conn.execute("DELETE FROM comparison_decisions WHERE tenant_id=$1 AND application_id=$2", tid, body.application_id)
        await conn.execute(
            "INSERT INTO comparison_decisions (application_id, tenant_id, accord_outcome, accord_confidence, "
            " accord_decided_at, manual_outcome, manual_decided_by, manual_reasoning, manual_decided_at, agreement, created_at) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$5,$9,$5)",
            body.application_id, tid, accord_outcome, accord_conf, now, body.manual_outcome,
            _uuid(user.get("user_id")), body.manual_reasoning, agreement)
    label = {"agree": "AGREEMENT", "accord_stricter": "DISAGREEMENT — Accord stricter",
             "accord_looser": "DISAGREEMENT — Accord looser", "disagree": "DISAGREEMENT"}[agreement]
    return {"ok": True, "accord_outcome": accord_outcome, "manual_outcome": body.manual_outcome,
            "agreement": agreement, "label": label}


# ── 3. Comparison report ────────────────────────────────────────────
def _detail(r) -> dict:
    return {
        "application_id": r["application_id"], "borrower": r.get("full_name") or r["application_id"],
        "description": r["agreement_details"], "accord_decision": r["accord_outcome"],
        "manual_decision": r["manual_outcome"], "resolution": r["resolution"],
    }


@router.get("/report")
async def report(tenant_id: str = Depends(get_tenant_id)) -> dict:
    _require_db()
    pool = await _get_pool()
    async with pool.acquire() as conn:
        period = await conn.fetchrow(
            "SELECT * FROM comparison_periods WHERE tenant_id=$1 ORDER BY started_at DESC LIMIT 1", tenant_id)
        if period is None:
            return {"active": False}
        rows = await conn.fetch(
            """SELECT cd.*, ap.full_name FROM comparison_decisions cd
               LEFT JOIN applications a ON a.application_id = cd.application_id
               LEFT JOIN applicants ap ON ap.applicant_id = a.applicant_id
               WHERE cd.tenant_id=$1 ORDER BY cd.created_at""", tenant_id)

    total = len(rows)
    counts = {"agree": 0, "accord_stricter": 0, "accord_looser": 0, "disagree": 0}
    for r in rows:
        counts[r["agreement"]] = counts.get(r["agreement"], 0) + 1
    agree = counts["agree"]

    accord_caught, manual_caught, disagreements = [], [], []
    for r in rows:
        if r["agreement"] == "agree":
            continue
        res = (r["resolution"] or "").lower()
        if res.startswith("accord was right"):
            accord_caught.append(_detail(r))
        elif r["agreement"] == "accord_looser" or res.startswith("manual caught"):
            manual_caught.append(_detail(r))
        else:
            disagreements.append(_detail(r))

    started = period["started_at"]
    day = (datetime.utcnow() - started).days + 1 if started else 1
    # weekly trend
    weeks: dict[int, dict] = {}
    for r in rows:
        wk = ((r["created_at"] - started).days // 7) + 1 if started and r["created_at"] else 1
        b = weeks.setdefault(wk, {"loans": 0, "agree": 0})
        b["loans"] += 1
        b["agree"] += 1 if r["agreement"] == "agree" else 0
    weekly_trend = [{"week": w, "loans": weeks[w]["loans"],
                     "agreement": round(weeks[w]["agree"] / weeks[w]["loans"] * 100, 1)} for w in sorted(weeks)]

    rate = round(agree / total * 100, 1) if total else 0.0
    ended = period["status"] == "completed"
    return {
        "active": not ended, "ended": ended,
        "period": {"started": _iso(started), "ends": _iso(period["ends_at"]),
                   "day": min(day, 90), "duration": 90},
        "summary": {
            "total_loans": total, "agree": agree, "accord_stricter": counts["accord_stricter"],
            "accord_looser": counts["accord_looser"], "disagree": counts["disagree"], "agreement_rate": rate,
        },
        "accord_caught": accord_caught, "manual_caught": manual_caught, "disagreements": disagreements,
        "weekly_trend": weekly_trend,
        "all_comparisons": [{
            "application_id": r["application_id"], "borrower": r["full_name"] or r["application_id"],
            "accord_outcome": r["accord_outcome"], "manual_outcome": r["manual_outcome"], "agreement": r["agreement"],
        } for r in rows],
    }


# ── Status: active period + whether this loan already has a comparison ──
@router.get("/status")
async def status(application_id: Optional[str] = None, tenant_id: str = Depends(get_tenant_id)) -> dict:
    _require_db()
    pool = await _get_pool()
    async with pool.acquire() as conn:
        period = await _active_period(conn, tenant_id)
        existing = None
        if application_id and period:
            row = await conn.fetchrow(
                "SELECT accord_outcome, manual_outcome, agreement FROM comparison_decisions WHERE tenant_id=$1 AND application_id=$2",
                tenant_id, application_id)
            existing = dict(row) if row else None
    return {
        "active": period is not None,
        "ends_at": _iso(period["ends_at"]) if period else None,
        "existing": existing,
    }


@router.post("/complete")
async def complete(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") not in ("admin", "manager"):
        raise HTTPException(403, "Admin or manager access required")
    _require_db()
    tid = user["tenant_id"]
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE comparison_periods SET status='completed', completed_at=NOW() WHERE tenant_id=$1 AND status='active'", tid)
    return {"ok": True}


def _uuid(v: Any):
    from uuid import UUID
    try:
        return UUID(str(v)) if v else None
    except (ValueError, TypeError):
        return None

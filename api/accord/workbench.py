"""Accord — underwriter workbench: documented human actions + similar-case lookup.

- POST/GET /loans/{id}/actions: the decision-notes thread (loan_actions). A human
  action requires a >= 25-char reason; that reasoning powers the examiner-readiness
  score and the similar-cases panel.
- GET /loans/{id}/similar-cases: other loans with documented actions whose
  fraud_score is close to this loan's, so an underwriter can see how comparable
  files were resolved and why.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.accord.auth import get_current_user
from api.accord.pipeline import _f, _get_pool, _J, _require_db

router = APIRouter(prefix="/api/accord", tags=["accord-workbench"])

# Default audiences per action type (used when the client doesn't specify).
_VISIBLE_DEFAULT: dict[str, list[str]] = {
    "refer_bsa": ["senior_uw", "compliance", "examiner", "bsa"],
    "deny": ["senior_uw", "compliance", "examiner"],
    "approve": ["senior_uw", "compliance", "examiner"],
    "escalate": ["senior_uw", "compliance"],
    "senior_review": ["senior_uw", "compliance"],
    "request_documents": ["senior_uw", "compliance"],
    "add_note": ["senior_uw", "compliance"],
}
# action_type -> short outcome label for the similar-cases panel.
_OUTCOME = {
    "refer_bsa": "BSA Referral", "deny": "Denied", "approve": "Approved",
    "request_documents": "Docs Requested", "senior_review": "Senior Review",
    "escalate": "Escalated", "add_note": "Note",
}


class LoanActionCreate(BaseModel):
    action_type: str
    reason_category: Optional[str] = None
    reason_text: str
    related_decision_id: Optional[str] = None
    visible_to: Optional[list[str]] = None


def _uid(v):
    from uuid import UUID
    try:
        return UUID(str(v)) if v else None
    except (ValueError, TypeError):
        return None


async def _route_senior_review(conn, application_id: str, user: dict) -> None:
    """On a senior_review action: hand the loan off to the tenant's senior UW
    (reassign the active loan_assignment, else create one) and notify them.
    Best-effort — a routing hiccup never blocks the action from being recorded."""
    try:
        tenant_id = user["tenant_id"]
        senior = await conn.fetchrow(
            "SELECT user_id, email, name FROM users "
            "WHERE tenant_id=$1 AND role='senior_uw' AND is_active=true ORDER BY name LIMIT 1",
            tenant_id)
        if senior is None:
            return
        actor = user.get("name") or user.get("email") or "an underwriter"
        note = f"Senior review requested by {actor}"
        by = _uid(user.get("user_id"))
        # Reassign the active assignment to the senior UW; if there isn't one, create it.
        res = await conn.execute(
            "UPDATE loan_assignments SET previous_assignee = assigned_to, assigned_to = $1, "
            "assigned_by = $2, handoff_notes = $3, assigned_at = NOW() "
            "WHERE application_id = $4 AND tenant_id = $5 AND status = 'active'",
            senior["user_id"], by, note, application_id, tenant_id)
        if res.strip().endswith(" 0"):
            await conn.execute(
                "INSERT INTO loan_assignments "
                "(application_id, tenant_id, assigned_to, assigned_by, stage, status, handoff_notes, assigned_at) "
                "VALUES ($1,$2,$3,$4,'underwriting','active',$5,NOW())",
                application_id, tenant_id, senior["user_id"], by, note)
        # Notify the senior UW.
        await conn.execute(
            "INSERT INTO notifications (user_id, tenant_id, type, title, body, application_id, created_at) "
            "VALUES ($1,$2,'senior_review_requested','Senior review requested',$3,$4,NOW())",
            senior["user_id"], tenant_id, f"{note} — {application_id}", application_id)
    except Exception:
        pass


def _action_view(r) -> dict:
    return {
        "id": str(r["id"]),
        "application_id": r["application_id"],
        "action_type": r["action_type"],
        "reason_category": r["reason_category"],
        "reason_text": r["reason_text"],
        "performed_by": r["performed_by"],
        "performed_at": r["performed_at"].isoformat() if r["performed_at"] else None,
        "related_decision_id": r["related_decision_id"],
        "visible_to": list(r["visible_to"]) if r["visible_to"] else [],
    }


@router.get("/loans/{application_id}/senior-uw")
async def get_senior_uw(application_id: str, user: dict = Depends(get_current_user)) -> dict:
    """The tenant's senior underwriter — shown in the escalate / senior-review
    modal so the underwriter sees who the file will be assigned to."""
    _require_db()
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT name, email FROM users "
            "WHERE tenant_id=$1 AND role='senior_uw' AND is_active=true ORDER BY name LIMIT 1",
            user["tenant_id"])
    return {"name": row["name"] if row else None, "email": row["email"] if row else None}


@router.get("/loans/{application_id}/actions")
async def list_actions(application_id: str, user: dict = Depends(get_current_user)) -> dict:
    _require_db()
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, application_id, action_type, reason_category, reason_text,
                      performed_by, performed_at, related_decision_id, visible_to
               FROM loan_actions WHERE application_id=$1 AND tenant_id=$2
               ORDER BY performed_at DESC""",
            application_id, user["tenant_id"])
    return {"actions": [_action_view(r) for r in rows]}


@router.post("/loans/{application_id}/actions")
async def create_action(application_id: str, body: LoanActionCreate, user: dict = Depends(get_current_user)) -> dict:
    if len((body.reason_text or "").strip()) < 25:
        raise HTTPException(422, "reason_text must be at least 25 characters")
    visible = body.visible_to or _VISIBLE_DEFAULT.get(body.action_type, ["senior_uw", "compliance"])
    _require_db()
    pool = await _get_pool()
    async with pool.acquire() as conn:
        r = await conn.fetchrow(
            """INSERT INTO loan_actions
                 (application_id, tenant_id, action_type, reason_category, reason_text,
                  performed_by, related_decision_id, visible_to)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
               RETURNING id, application_id, action_type, reason_category, reason_text,
                         performed_by, performed_at, related_decision_id, visible_to""",
            application_id, user["tenant_id"], body.action_type, body.reason_category,
            body.reason_text.strip(), user.get("email") or user.get("user_id"),
            body.related_decision_id, visible)
        # Senior-review hands the loan off to the tenant's senior UW + notifies them.
        if body.action_type == "senior_review":
            await _route_senior_review(conn, application_id, user)
    return _action_view(r)


@router.get("/loans/{application_id}/similar-cases")
async def similar_cases(application_id: str, user: dict = Depends(get_current_user)) -> dict:
    _require_db()
    pool = await _get_pool()
    tenant_id = user["tenant_id"]
    async with pool.acquire() as conn:
        es = await conn.fetchrow(
            "SELECT borrower, loan_terms, loan_amount FROM entity_states WHERE application_id=$1 AND tenant_id=$2",
            application_id, tenant_id)
        if es is None:
            raise HTTPException(404, f"Unknown application {application_id}")
        b = _J(es["borrower"]) or {}
        cur_fraud = _f((b.get("identity") or {}).get("fraud_score"))
        cur_type = (_J(es["loan_terms"]) or {}).get("loan_type")

        # Candidates: loans with a documented action + a fraud score. Search this
        # tenant first, then fall back to any tenant if we can't field 3.
        async def candidates(scope_tenant: bool):
            return await conn.fetch(
                f"""SELECT DISTINCT ON (la.application_id)
                        la.application_id, la.action_type, la.reason_text, la.reason_category,
                        la.performed_at, la.related_decision_id,
                        (es2.borrower->'identity'->>'fraud_score')::float AS fraud_score,
                        es2.loan_amount, es2.loan_terms->>'loan_type' AS loan_type, es2.created_at
                    FROM loan_actions la
                    JOIN entity_states es2 ON es2.application_id=la.application_id AND es2.tenant_id=la.tenant_id
                    WHERE la.application_id <> $1
                      AND (es2.borrower->'identity'->>'fraud_score') IS NOT NULL
                      {"AND la.tenant_id=$2" if scope_tenant else ""}
                    ORDER BY la.application_id, la.performed_at DESC""",
                *( (application_id, tenant_id) if scope_tenant else (application_id,) ))

        rows = await candidates(True)
        if len(rows) < 3:
            extra = await candidates(False)
            seen = {r["application_id"] for r in rows}
            rows = list(rows) + [r for r in extra if r["application_id"] not in seen]

    def closeness(r):
        f = _f(r["fraud_score"])
        diff = abs((f or 0) - (cur_fraud or 0))
        same_type = 0 if (cur_type and r["loan_type"] == cur_type) else 1
        return (same_type, diff)

    ranked = sorted(rows, key=closeness)
    # Keep reasonably-similar matches (fraud within 0.30); the closest 3.
    cases = []
    for r in ranked:
        f = _f(r["fraud_score"])
        if cur_fraud is not None and f is not None and abs(f - cur_fraud) > 0.30:
            continue
        resolved_days = None
        if r["created_at"] and r["performed_at"]:
            resolved_days = max(0, (r["performed_at"] - r["created_at"]).days)
        cases.append({
            "application_id": r["application_id"],
            "loan_amount": _f(r["loan_amount"]),
            "fraud_score": f,
            "loan_type": r["loan_type"],
            "outcome": _OUTCOME.get(r["action_type"], r["action_type"]),
            "action_type": r["action_type"],
            "reason_text": r["reason_text"],
            "reason_category": r["reason_category"],
            "related_decision_id": r["related_decision_id"],
            "resolved_days": resolved_days,
        })
        if len(cases) >= 3:
            break

    return {"cases": cases, "based_on": {"fraud_score": cur_fraud, "loan_type": cur_type}}

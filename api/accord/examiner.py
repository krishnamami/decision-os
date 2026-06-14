"""Accord — examiner package: a one-click, full decision-trail export per loan.

A compliance officer responding to a regulatory exam (CFPB ECOA/Reg B, HMDA,
TILA; OCC / FDIC compliance manuals) needs the complete decision documentation
for one loan in a single, printable artifact. This endpoint returns the full
loan-detail payload (borrower, metrics, QM, decisions with rules + evidence,
documents, audit log, conditions) plus loan_type, stamped with who generated it
and when. The frontend renders it as a printable report.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from api.accord.auth import get_current_user
from api.accord.pipeline import _get_pool, _require_db, loan_detail

router = APIRouter(prefix="/api/accord", tags=["accord-examiner"])

# Examiner packages are a compliance artifact — restricted to compliance/admin.
_ALLOWED_ROLES = {"compliance", "admin", "super_admin"}


@router.get("/loans/{application_id}/examiner-report")
async def examiner_report(application_id: str, user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") not in _ALLOWED_ROLES:
        raise HTTPException(403, "Compliance or admin role required")
    tenant_id = user["tenant_id"]

    # Full loan detail (raises 404 if the loan isn't in this tenant).
    loan = await loan_detail(application_id, tenant_id=tenant_id)

    # loan_type isn't in the loan-detail payload — pull it from entity_states.
    _require_db()
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT loan_terms->>'loan_type' AS loan_type FROM entity_states "
            "WHERE application_id=$1 AND tenant_id=$2",
            application_id, tenant_id,
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_by": user.get("email") or user.get("user_id"),
        "application_id": application_id,
        "tenant_id": tenant_id,
        "loan_type": row["loan_type"] if row else None,
        "loan": loan,
    }

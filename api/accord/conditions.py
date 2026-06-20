"""
Conditions API — CN-C

GET   /api/accord/conditions/{application_id}
      All conditions for a loan (filter: prior_to, status)

GET   /api/accord/conditions/{application_id}/summary
      Aggregate counts (loan-officer / UW view)

PATCH /api/accord/conditions/{condition_id}/satisfy
      Mark condition satisfied + link document

PATCH /api/accord/conditions/{condition_id}/waive
      Waive condition (governance action)

Conventions match the rest of the Accord API: tenant comes from the JWT
(get_tenant_id), DB access via _require_db()/_get_pool(), and the router is
mounted under /api/accord. Reads loan_condition_instances (CN-A) via the
CN-C summary/aggregate views.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.accord.auth import get_tenant_id
from api.accord.pipeline import _get_pool, _require_db

router = APIRouter(prefix="/api/accord/conditions", tags=["accord-conditions"])


class SatisfyRequest(BaseModel):
    document_id: str
    reviewed_by: str
    review_notes: Optional[str] = ""


class WaiveRequest(BaseModel):
    waived_by: str
    waive_notes: str


def _iso(v: Any) -> Any:
    return v.isoformat() if hasattr(v, "isoformat") else v


def _row(r: Any) -> dict:
    """asyncpg Record -> JSON-safe dict (datetimes -> iso)."""
    return {k: _iso(v) for k, v in dict(r).items()}


@router.get("/{application_id}")
async def get_conditions(
    application_id: str,
    prior_to: Optional[str] = None,
    status: Optional[str] = None,
    tenant_id: str = Depends(get_tenant_id),
) -> list[dict]:
    """All conditions for a loan, blocking first then by due date."""
    _require_db()
    pool = await _get_pool()
    async with pool.acquire() as conn:
        query = """
            SELECT *
            FROM vw_loan_condition_summary
            WHERE application_id = $1
            AND tenant_id = $2
        """
        params: list[Any] = [application_id, tenant_id]
        if prior_to:
            params.append(prior_to)
            query += f" AND prior_to = ${len(params)}"
        if status:
            params.append(status)
            query += f" AND status = ${len(params)}"
        query += " ORDER BY blocks_closing DESC, due_date ASC"
        rows = await conn.fetch(query, *params)
        return [_row(r) for r in rows]


@router.get("/{application_id}/summary")
async def get_conditions_summary(
    application_id: str,
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    """Aggregate condition counts for a loan."""
    _require_db()
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT *
            FROM vw_loan_conditions_aggregate
            WHERE application_id = $1
            AND tenant_id = $2
            """,
            application_id,
            tenant_id,
        )
        if not row:
            return {
                "application_id": application_id,
                "tenant_id": tenant_id,
                "total_conditions": 0,
                "open_conditions": 0,
                "blocking_conditions": 0,
                "cleared_conditions": 0,
                "overdue_conditions": 0,
            }
        return _row(row)


async def _condition_tenant(conn, condition_id: str) -> Optional[str]:
    """Tenant guard — confirm the condition belongs to the caller's tenant."""
    try:
        return await conn.fetchval(
            "SELECT tenant_id FROM loan_condition_instances WHERE id = $1::uuid",
            condition_id,
        )
    except Exception:
        return None


@router.patch("/{condition_id}/satisfy")
async def satisfy_condition(
    condition_id: str,
    body: SatisfyRequest,
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    """Mark condition satisfied: approve + record satisfying document."""
    _require_db()
    pool = await _get_pool()
    async with pool.acquire() as conn:
        owner = await _condition_tenant(conn, condition_id)
        if owner is None:
            raise HTTPException(status_code=404, detail="Condition not found")
        if owner != tenant_id:
            raise HTTPException(status_code=403, detail="Wrong tenant")
        from core.conditions.condition_engine import ConditionEngine

        engine = ConditionEngine(conn)
        await engine.satisfy_condition(
            condition_id=condition_id,
            document_id=body.document_id,
            reviewed_by=body.reviewed_by,
            review_notes=body.review_notes or "",
        )
        return {"status": "approved", "condition_id": condition_id}


@router.patch("/{condition_id}/waive")
async def waive_condition(
    condition_id: str,
    body: WaiveRequest,
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    """Waive a condition (governance action)."""
    _require_db()
    pool = await _get_pool()
    async with pool.acquire() as conn:
        owner = await _condition_tenant(conn, condition_id)
        if owner is None:
            raise HTTPException(status_code=404, detail="Condition not found")
        if owner != tenant_id:
            raise HTTPException(status_code=403, detail="Wrong tenant")
        await conn.execute(
            """
            UPDATE loan_condition_instances
            SET status = 'waived',
                cleared_at = NOW(),
                notes = $2,
                updated_at = NOW()
            WHERE id = $1::uuid
            """,
            condition_id,
            body.waive_notes,
        )
        return {"status": "waived", "condition_id": condition_id}

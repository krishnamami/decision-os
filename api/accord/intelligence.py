"""Accord — intelligence endpoints (change-impact simulation, CI-A).

Read-only "what-if" analytics over the recorded pipeline. POST a hypothetical
overlay-rule value and get the projected pipeline impact — which applications
would flip, the dollars unblocked / at risk, and an honest accounting of the
apps that stay blocked on OTHER constraints. NEVER writes the catalogue or any
decision. Reuses the accord asyncpg pool.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.accord.auth import get_tenant_id
from api.accord.pipeline import _get_pool, _require_db
from core.intelligence.change_impact_simulator import (
    SIMULATABLE_FIELDS,
    ChangeImpactSimulator,
)

router = APIRouter(prefix="/api/accord/intelligence", tags=["accord-intelligence"])


class SimulateImpactBody(BaseModel):
    rule_name: str
    hypothetical_value: float
    loan_type: str = "conventional"
    # optional override; if omitted we read the live overlay value (display-only)
    current_value: Optional[float] = None


@router.get("/simulatable-rules")
async def simulatable_rules(tenant_id: str = Depends(get_tenant_id)) -> dict:
    """The overlay levers this tenant can simulate + their current values."""
    _require_db()
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT rule_type, loan_type, overlay_value, direction, is_active
               FROM overlay_rules WHERE tenant_id = $1 AND is_active = true
               ORDER BY rule_type, loan_type""",
            tenant_id,
        )
    levers = []
    for r in rows:
        if r["rule_type"] in SIMULATABLE_FIELDS:
            entity_field, persona, gate = SIMULATABLE_FIELDS[r["rule_type"]]
            levers.append({
                "rule_name": r["rule_type"],
                "loan_type": r["loan_type"],
                "current_value": float(r["overlay_value"]),
                "entity_field": entity_field,
                "controlled_persona": persona,
                "gate": gate,
            })
    return {"tenant_id": tenant_id, "simulatable_rules": levers}


@router.post("/simulate-impact")
async def simulate_impact(
    body: SimulateImpactBody,
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    """Project the pipeline impact of moving one overlay rule. Read-only."""
    _require_db()
    if body.rule_name not in SIMULATABLE_FIELDS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown rule_name {body.rule_name!r}; "
                   f"simulatable: {list(SIMULATABLE_FIELDS)}",
        )

    pool = await _get_pool()
    async with pool.acquire() as conn:
        current_value = body.current_value
        if current_value is None:
            row = await conn.fetchrow(
                """SELECT overlay_value FROM overlay_rules
                   WHERE tenant_id = $1 AND rule_type = $2 AND loan_type = $3
                     AND is_active = true
                   ORDER BY created_at DESC LIMIT 1""",
                tenant_id, body.rule_name, body.loan_type,
            )
            if row is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"No active overlay '{body.rule_name}' / "
                           f"'{body.loan_type}' for tenant {tenant_id}; "
                           f"pass current_value explicitly to simulate anyway.",
                )
            current_value = float(row["overlay_value"])

        result = await ChangeImpactSimulator().simulate(
            conn, tenant_id, body.rule_name, current_value, body.hypothetical_value,
        )
    return result

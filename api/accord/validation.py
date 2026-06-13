"""Accord — rule validation API.

Runs the boundary test suite (core.compliance.rule_validator) for the current
tenant's active rules and exposes the results so customers can see them and
examiners can download them. Answers "how do I KNOW 43.1% DTI gets blocked?".
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from api.accord.auth import get_tenant_id
from api.accord.pipeline import _get_pool, _require_db
from core.compliance.rule_validator import RuleValidator

router = APIRouter(prefix="/api/accord/rules", tags=["accord-validation"])

# In-memory cache of the last run per tenant (the suite is deterministic + fast).
_LAST: dict[str, dict] = {}


def _jsonb(v: Any) -> Any:
    if isinstance(v, (dict, list)) or v is None:
        return v
    try:
        return json.loads(v)
    except (TypeError, ValueError):
        return {}


async def run_validation(tenant_id: str, proposed_rules: dict | None = None, programs: list | None = None, version: int | None = None) -> dict:
    """Run the suite. If proposed_rules given, validate those (for pre-activation
    checks); otherwise load the tenant's active version."""
    _require_db()
    if proposed_rules is None:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT version, rules, programs FROM tenant_rules WHERE tenant_id=$1 AND status='active'", tenant_id)
        if row is None:
            raise HTTPException(404, "No active rules to validate")
        proposed_rules = _jsonb(row["rules"])
        programs = _jsonb(row["programs"]) or ["conventional", "fha"]
        version = row["version"]
    t0 = time.monotonic()
    rep = RuleValidator(tenant_id, proposed_rules, programs or ["conventional", "fha"], version).run_all()
    rep["duration_ms"] = round((time.monotonic() - t0) * 1000, 1)
    rep["run_at"] = datetime.utcnow().isoformat() + "Z"
    return rep


@router.post("/validate")
async def validate(tenant_id: str = Depends(get_tenant_id)) -> dict:
    rep = await run_validation(tenant_id)
    _LAST[tenant_id] = rep
    return rep


@router.get("/validation-report")
async def validation_report(tenant_id: str = Depends(get_tenant_id)) -> dict:
    if tenant_id not in _LAST:
        _LAST[tenant_id] = await run_validation(tenant_id)
    return _LAST[tenant_id]

"""Accord — QA / compliance-assurance endpoints (read-only, admin/compliance).

QA-A fair-lending regression (the demographics-never-used ECOA invariant guard).
Further QA endpoints (backtesting, security audit) mount here as they ship.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from api.accord.auth import get_current_user
from api.accord.pipeline import _get_pool, _require_db

router = APIRouter(prefix="/api/accord/qa", tags=["accord-qa"])


def _require_admin_compliance(user: dict) -> None:
    if user.get("role") not in ("admin", "compliance", "super_admin"):
        raise HTTPException(403, "Admin or compliance access required")


@router.get("/fair-lending-regression")
async def fair_lending_regression(user: dict = Depends(get_current_user)) -> dict:
    """Paired fair-lending regression: swap protected-class proxies and confirm
    byte-identical outcomes (ECOA 12 CFR 202). Read-only; no DB. Compliance audit trail."""
    _require_admin_compliance(user)
    from core.qa.fair_lending_regression import FairLendingRegressionHarness
    return FairLendingRegressionHarness().run_all()


@router.get("/backtest")
async def model_backtest(year: Optional[int] = Query(None),
                         user: dict = Depends(get_current_user)) -> dict:
    """SR 11-7 model accuracy backtesting: compare decisions against actual loan
    performance. Returns insufficient_data until a loan_performance table is
    populated. Admin/compliance; read-only."""
    _require_admin_compliance(user)
    _require_db()
    from core.qa.backtesting import ModelAccuracyBacktester, fetch_backtest_data
    tenant_id = user["tenant_id"]
    pool = await _get_pool()
    async with pool.acquire() as conn:
        decisions, perf = await fetch_backtest_data(conn, tenant_id, year)
    return ModelAccuracyBacktester().backtest(
        decisions=decisions, performance_labels=perf, tenant_id=tenant_id,
        period=str(year) if year else "all")


@router.get("/security-audit")
async def security_audit(user: dict = Depends(get_current_user)) -> dict:
    """Platform security posture report (SOC 2 + OWASP + RLS/tenant isolation).
    Verifiable controls computed live; process controls flagged manual_review.
    Admin/super_admin only; read-only."""
    if user.get("role") not in ("admin", "super_admin"):
        raise HTTPException(403, "Admin access required")
    _require_db()
    from core.qa.security_audit import SecurityAuditor, fetch_security_audit_data
    pool = await _get_pool()
    async with pool.acquire() as conn:
        facts = await fetch_security_audit_data(conn)
    return SecurityAuditor().assess(facts)


__all__ = ["router"]

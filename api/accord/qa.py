"""Accord — QA / compliance-assurance endpoints (read-only, admin/compliance).

QA-A fair-lending regression (the demographics-never-used ECOA invariant guard).
Further QA endpoints (backtesting, security audit) mount here as they ship.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api.accord.auth import get_current_user

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


__all__ = ["router"]

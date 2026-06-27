"""Accord — model risk management endpoints (SR 11-7). Read-only, admin/compliance.

MR-A: model cards + validation status over the 14 decision personas. MR-B endpoints
(inventory + monitoring) mount here as they ship.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api.accord.auth import get_current_user

router = APIRouter(prefix="/api/accord/model-risk", tags=["accord-model-risk"])


def _require(user: dict) -> None:
    if user.get("role") not in ("admin", "compliance", "super_admin"):
        raise HTTPException(403, "Admin or compliance access required")


@router.get("/cards")
async def model_cards(user: dict = Depends(get_current_user)) -> dict:
    """All 14 SR 11-7 model cards + portfolio tier roll-up. Read-only."""
    _require(user)
    from core.model_risk.model_card import ModelCardGenerator
    return ModelCardGenerator().generate_all_cards()


@router.get("/validation-status")
async def validation_status(user: dict = Depends(get_current_user)) -> dict:
    """Validation status + review schedule across the 14 models. Read-only."""
    _require(user)
    from core.model_risk.model_card import ModelCardGenerator
    return ModelCardGenerator().validation_status()


@router.get("/cards/{model_id}")
async def model_card(model_id: str, user: dict = Depends(get_current_user)) -> dict:
    """Full SR 11-7 card for one model. 404 if unknown. Read-only."""
    _require(user)
    from core.model_risk.model_card import ModelCardGenerator
    card = ModelCardGenerator().generate_card(model_id)
    if card.get("status") == "not_found":
        raise HTTPException(404, f"No model card for '{model_id}'")
    return card


__all__ = ["router"]

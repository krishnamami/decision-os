"""Accord — model risk management endpoints (SR 11-7). Read-only, admin/compliance.

MR-A: model cards + validation status over the 14 decision personas. MR-B endpoints
(inventory + monitoring) mount here as they ship.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api.accord.auth import get_current_user, get_tenant_id
from api.accord.pipeline import _get_pool, _require_db

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


@router.get("/inventory")
async def inventory(user: dict = Depends(get_current_user)) -> dict:
    """Model inventory roll-up (MR-B): the 14 models by tier/owner + monitoring plan."""
    _require(user)
    from core.model_risk.inventory import build_inventory
    return build_inventory()


@router.get("/monitoring")
async def monitoring(tenant_id: str = Depends(get_tenant_id),
                     user: dict = Depends(get_current_user)) -> dict:
    """Ongoing monitoring (MR-B): input-distribution drift (PSI) for the drift-capable
    models + accuracy (QA-B) + champion/challenger (CI-B). Read-only."""
    _require(user)
    _require_db()
    from core.model_risk.drift import DRIFT_FEATURES, detect_drift, fetch_feature_windows
    from core.model_risk.inventory import assess_model_monitoring
    pool = await _get_pool()
    results = {}
    async with pool.acquire() as conn:
        for model_id, feature in DRIFT_FEATURES.items():
            baseline, recent = await fetch_feature_windows(conn, tenant_id, model_id, feature)
            drift = detect_drift(baseline, recent)
            drift["feature"] = feature
            results[model_id] = assess_model_monitoring(model_id, drift=drift)
    attention = [m for m, r in results.items() if r["overall_monitoring_status"] == "attention"]
    return {
        "tenant_id": tenant_id, "models_monitored": list(results),
        "attention": attention, "monitoring": results,
        "note": ("Drift is real (recorded input distributions); accuracy reuses QA-B "
                 "(insufficient_data without loan_performance); champion/challenger reuses CI-B."),
        "citation": "SR 11-7 ongoing monitoring",
        "data_source": "decision_outputs.context_snapshot + QA-B + CI-B",
        "missing_inputs": sorted({m for r in results.values() for m in r["missing_inputs"]}),
    }


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

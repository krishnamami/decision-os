"""MR-B — model inventory + ongoing-monitoring roll-up (SR 11-7).

Inventory = a portfolio roll-up of the MR-A model cards (the registry). Monitoring
combines, per model: input-distribution DRIFT (drift.py, real), ACCURACY (reuse
QA-B ModelAccuracyBacktester — insufficient_data without a loan_performance table),
and CHAMPION/CHALLENGER (reuse CI-B decision_replay against a different rule version).

Pure assembly (build_inventory / assess_model_monitoring); the drift + accuracy I/O
live in their own modules. Read-only -> 16/16 by construction.
"""
from __future__ import annotations

from typing import Optional


def build_inventory() -> dict:
    """Portfolio roll-up of the 14 model cards (MR-A registry)."""
    from core.model_risk.model_card import MODEL_REGISTRY
    items = [{
        "model_id": c["model_id"], "name": c["name"], "type": c["type"],
        "wave": c["wave"], "mode": c["mode"], "risk_tier": c["risk_tier"],
        "owner_team": c["owner_team"], "approval_status": c["approval_status"],
        "last_review": c["last_review"], "next_review": c["next_review"],
    } for c in MODEL_REGISTRY.values()]
    by_tier = {t: [i["model_id"] for i in items if i["risk_tier"] == t]
               for t in ("high", "medium", "low")}
    return {
        "total_models": len(items),
        "by_tier": {t: len(v) for t, v in by_tier.items()},
        "by_owner": _group(items, "owner_team"),
        "items": items,
        "monitoring_plan": {
            "high": "quarterly drift review + annual validation",
            "medium": "semi-annual drift review + biennial validation",
            "low": "annual drift review",
        },
        "citation": "SR 11-7 Model Risk Management",
        "data_source": "MODEL_REGISTRY (MR-A)", "missing_inputs": [],
    }


def _group(items, key) -> dict:
    out: dict = {}
    for i in items:
        out.setdefault(i[key], []).append(i["model_id"])
    return {k: len(v) for k, v in out.items()}


def assess_model_monitoring(model_id: str, drift: Optional[dict] = None,
                            accuracy: Optional[dict] = None) -> dict:
    """Combine the three SR 11-7 ongoing-monitoring dimensions for one model.
    drift: from detect_drift (or None -> not assessed). accuracy: from QA-B
    backtest() (typically insufficient_data). champion/challenger -> CI-B replay."""
    drift_status = (drift or {}).get("status", "not_assessed")
    acc_status = (accuracy or {}).get("status", "not_assessed")

    if drift_status == "significant_drift":
        overall = "attention"
    elif drift_status == "moderate_drift":
        overall = "watch"
    elif drift_status in ("no_drift",):
        overall = "healthy"
    else:
        overall = "insufficient_data"

    missing = []
    if drift_status in ("insufficient_data", "not_assessed"):
        missing.append(f"{model_id}: drift not assessable (insufficient recorded inputs)")
    if acc_status != "complete":
        missing.append(f"{model_id}: accuracy backtest {acc_status} (needs loan_performance — QA-B)")

    return {
        "model_id": model_id, "overall_monitoring_status": overall,
        "drift": drift or {"status": "not_assessed"},
        "accuracy": {"status": acc_status,
                     "note": "QA-B ModelAccuracyBacktester — reuse; no loan_performance table yet"},
        "champion_challenger": {
            "status": "available",
            "note": "Reuse CI-B decision_replay to score this model under a different "
                    "tenant_rules version (challenger). Real once >=2 rule versions exist."},
        "citation": "SR 11-7 ongoing monitoring",
        "data_source": "drift.py + QA-B backtesting + CI-B replay",
        "missing_inputs": missing,
    }


__all__ = ["build_inventory", "assess_model_monitoring"]

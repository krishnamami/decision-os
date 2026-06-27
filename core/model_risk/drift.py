"""MR-B — input-distribution drift detection (PSI) over recorded decisions.

Population Stability Index (PSI) between a baseline window and a recent window of a
model's input feature (from decision_outputs.context_snapshot). Standard bands:
  PSI < 0.10  -> no_drift
  0.10-0.25   -> moderate drift (monitor)
  >= 0.25     -> significant drift (investigate / revalidate)

Pure compute (compute_psi / detect_drift) is DB-free + unit-tested; fetch helpers do
the I/O. Read-only -> 16/16 by construction. Equal-width bins over the combined range
(deterministic + simple) with an epsilon floor so empty bins don't blow up the log.
"""
from __future__ import annotations

import math
from typing import Optional

# context_snapshot feature key per drift-capable model (confirmed real keys).
DRIFT_FEATURES = {
    "credit_assessment": "credit_score",
    "dti_calculation": "dti_ratio",
    "ltv_assessment": "ltv",
}
_EPS = 1e-6
NO_DRIFT_MAX = 0.10
MODERATE_MAX = 0.25


def _floats(values) -> list:
    out = []
    for v in values or []:
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            continue
    return out


def compute_psi(baseline, recent, n_bins: int = 10) -> Optional[float]:
    """PSI between two samples using equal-width bins over the combined range.
    Returns None when either sample is empty or has no spread."""
    b = _floats(baseline)
    r = _floats(recent)
    if not b or not r:
        return None
    lo, hi = min(b + r), max(b + r)
    if hi <= lo:
        return 0.0  # no spread -> identical -> no drift
    width = (hi - lo) / n_bins

    def _props(sample):
        counts = [0] * n_bins
        for v in sample:
            idx = min(int((v - lo) / width), n_bins - 1)
            counts[idx] += 1
        total = len(sample)
        return [max(c / total, _EPS) for c in counts]

    bp, rp = _props(b), _props(r)
    return round(sum((rp[i] - bp[i]) * math.log(rp[i] / bp[i]) for i in range(n_bins)), 4)


def detect_drift(baseline, recent, n_bins: int = 10) -> dict:
    """PSI + classification. RULE 11: insufficient_data when a window is too small."""
    b, r = _floats(baseline), _floats(recent)
    if len(b) < 10 or len(r) < 10:
        return {"status": "insufficient_data", "psi": None,
                "n_baseline": len(b), "n_recent": len(r),
                "reason": "each window needs >= 10 observations for a meaningful PSI",
                "data_source": "decision_outputs.context_snapshot",
                "missing_inputs": ["insufficient sample for drift PSI"]}
    psi = compute_psi(b, r, n_bins)
    if psi is None:
        status = "insufficient_data"
    elif psi < NO_DRIFT_MAX:
        status = "no_drift"
    elif psi < MODERATE_MAX:
        status = "moderate_drift"
    else:
        status = "significant_drift"
    return {"status": status, "psi": psi, "n_baseline": len(b), "n_recent": len(r),
            "thresholds": {"no_drift_max": NO_DRIFT_MAX, "moderate_max": MODERATE_MAX},
            "note": ("PSI on equal-width bins over the input feature; significant drift -> "
                     "revalidate the model (SR 11-7 ongoing monitoring)."),
            "data_source": "decision_outputs.context_snapshot", "missing_inputs": []}


async def fetch_feature_windows(conn, tenant_id: str, decision_id: str,
                                feature_key: str) -> tuple:
    """Split this model's recorded decisions at the median created_at into a baseline
    (older) and recent window, extracting context_snapshot->>feature_key as float.
    Returns (baseline_values, recent_values)."""
    rows = await conn.fetch(
        "SELECT created_at, (context_snapshot->>$3) AS val FROM decision_outputs "
        "WHERE tenant_id=$1 AND decision_id=$2 AND context_snapshot ? $3 "
        "ORDER BY created_at", tenant_id, decision_id, feature_key)
    vals = [(r["created_at"], r["val"]) for r in rows if r["val"] is not None]
    if not vals:
        return [], []
    mid = len(vals) // 2
    baseline = [v for _, v in vals[:mid]]
    recent = [v for _, v in vals[mid:]]
    return baseline, recent


__all__ = ["compute_psi", "detect_drift", "fetch_feature_windows", "DRIFT_FEATURES",
           "NO_DRIFT_MAX", "MODERATE_MAX"]

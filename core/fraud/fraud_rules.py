"""Fraud-detector threshold loader (RA-4F).

The fraud detectors used to hardcode their severity thresholds. They now read
them from the catalogue (agency_guidelines) via rule_loader. Unlike the sync
domain resolvers (RA-4A..D) the detectors are ASYNC and already hold a `conn`,
so they self-load these rules (no runner->bundle injection) — `load_fraud_rules`
is the single entry point, mirroring `load_*_rules` elsewhere.

  income_mismatch_{medium,high,critical}_pct   Fannie B3-3.1-01 / QC  (percent)
  undisclosed_debt_{medium,high,critical}_mo    Fannie B3-6-02         ($/month)

Employment/occupancy fraud has NO catalogued numeric threshold (its signals are
classifier-driven — stop-words, vacation-state set, name overlap), so nothing
from employment_fraud_detector resolves here.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# The catalogue keys the detectors consume (all governed_by=agency, verified vs
# live RDS — snake_case here, unlike the human-named rule_validator rows).
FRAUD_RULE_KEYS = [
    "income_mismatch_medium_pct",
    "income_mismatch_high_pct",
    "income_mismatch_critical_pct",
    "undisclosed_debt_medium_mo",
    "undisclosed_debt_high_mo",
    "undisclosed_debt_critical_mo",
]


async def load_fraud_rules(conn, tenant_id: str, agency: str = "fannie") -> dict:
    """Resolve the fraud-detector thresholds from the catalogue. Returns
    ``{'values': {key: float}, 'trace': {key: {governed_by, layers}}}``.

    No resolver-local fallback: a missing row falls through rule_loader's
    SAFE_DEFAULTS (the only sanctioned fallback) and is logged."""
    from core.catalogue.rule_loader import get_rule
    values, trace = {}, {}
    for key in FRAUD_RULE_KEYS:
        r = await get_rule(conn, key, tenant_id, agency=agency)
        values[key] = r.get("applied")
        trace[key] = {
            "applied":     r.get("applied"),
            "governed_by": r.get("governed_by"),
            "layers":      sorted((r.get("layers") or {}).keys()),
        }
        if r.get("governed_by") in ("safe_default", "SAFE_DEFAULT") or r.get("using_default"):
            logger.warning("FraudDetector: %s resolved via SAFE_DEFAULT — check catalogue", key)
    return {"values": values, "trace": trace}

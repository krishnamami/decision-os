"""Fraud subsystem — signal detection across income, employment, occupancy,
and undisclosed-debt dimensions; writes to fraud_signals."""
from .income_mismatch_detector import (
    IncomeMismatchDetector,
    MISMATCH_THRESHOLDS,
)

__all__ = ["IncomeMismatchDetector", "MISMATCH_THRESHOLDS"]

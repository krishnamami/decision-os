"""Fraud subsystem — signal detection across income, employment, occupancy,
and undisclosed-debt dimensions; writes to fraud_signals. Detector severity
thresholds resolve from the catalogue via load_fraud_rules (RA-4F)."""
from .fraud_rules import FRAUD_RULE_KEYS, load_fraud_rules
from .income_mismatch_detector import IncomeMismatchDetector, MISMATCH_TIERS
from .undisclosed_debt_detector import UndisclosedDebtDetector, UNDISCLOSED_TIERS
from .employment_fraud_detector import EmploymentFraudDetector

__all__ = [
    "IncomeMismatchDetector", "MISMATCH_TIERS",
    "UndisclosedDebtDetector", "UNDISCLOSED_TIERS",
    "EmploymentFraudDetector",
    "load_fraud_rules", "FRAUD_RULE_KEYS",
]

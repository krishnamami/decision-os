"""Exception framework (EX-A) — structured underwriting-exception eligibility +
compensating-factors model, layered on the existing override capture
(loan_actions + decision_outputs.human_*). Advisory."""
from core.exceptions.exception_engine import (
    EXCEPTION_RULE_KEYS,
    ExceptionEngine,
    load_exception_rules,
)

__all__ = ["ExceptionEngine", "EXCEPTION_RULE_KEYS", "load_exception_rules"]

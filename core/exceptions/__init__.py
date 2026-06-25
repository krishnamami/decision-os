"""Exception framework (EX-A) — structured underwriting-exception eligibility +
compensating-factors model, layered on the existing override capture
(loan_actions + decision_outputs.human_*). Advisory."""
from core.exceptions.compensating_factors_engine import (
    COMPENSATING_FACTOR_RULE_KEYS,
    CompensatingFactorsEngine,
    load_compensating_factor_rules,
)
from core.exceptions.exception_engine import (
    EXCEPTION_RULE_KEYS,
    ExceptionEngine,
    load_exception_rules,
)
from core.exceptions.exception_workflow import (
    APPROVER_AUTHORITY,
    ExceptionWorkflowService,
)
from core.exceptions.exception_writer import populate_exception_records

__all__ = [
    "ExceptionEngine", "EXCEPTION_RULE_KEYS", "load_exception_rules",
    "CompensatingFactorsEngine", "COMPENSATING_FACTOR_RULE_KEYS",
    "load_compensating_factor_rules",
    "ExceptionWorkflowService", "APPROVER_AUTHORITY",
    "populate_exception_records",
]

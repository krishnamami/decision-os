"""Obligations subsystem (OB-A) — per-type monthly debt-obligation resolution
feeding the DTI workbench breakdown (advisory)."""
from core.obligations.obligation_resolver import (
    OBLIGATION_RULE_KEYS,
    ObligationResolver,
    load_obligation_rules,
)

__all__ = ["ObligationResolver", "OBLIGATION_RULE_KEYS", "load_obligation_rules"]

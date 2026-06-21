"""Catalogue layer — shared rule loader.

Resolvers read thresholds from the catalogue tables (agency_guidelines,
platform_guardrails) via this module instead of hardcoding dicts. A missing
rule degrades to a SAFE_DEFAULT with a WARNING — never a crash, never silently
wrong.
"""
from .rule_loader import (
    SAFE_DEFAULTS,
    get_rule,
    load_rules,
    load_guardrails,
)

__all__ = [
    "SAFE_DEFAULTS",
    "get_rule",
    "load_rules",
    "load_guardrails",
]

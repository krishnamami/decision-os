"""Catalogue layer — shared rule loader.

Resolvers read thresholds from the catalogue tables (regulatory_rules,
agency_guidelines, overlay_rules) via this module instead of hardcoding dicts.
3-layer resolution (overlay applied, regulatory/agency as risk references),
Type 2 point-in-time, SAFE_DEFAULT + WARNING when a rule is missing.
"""
from .rule_loader import (
    SAFE_DEFAULTS,
    OVERLAY_ALIASES,
    get_rule,
    get_catalogue_value,
    load_rules,
)

__all__ = [
    "SAFE_DEFAULTS",
    "OVERLAY_ALIASES",
    "get_rule",
    "get_catalogue_value",
    "load_rules",
]

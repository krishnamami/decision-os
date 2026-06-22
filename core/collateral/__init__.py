"""Collateral subsystem — property eligibility, warrantability, flood zone,
and appraisal gap analysis."""
from .property_eligibility_resolver import (
    FANNIE_SPECIAL_TYPES,
    PropertyEligibilityResolver,
    PropertyEligibilityResult,
    load_collateral_rules,
)

__all__ = [
    "PropertyEligibilityResolver",
    "PropertyEligibilityResult",
    "FANNIE_SPECIAL_TYPES",
    "load_collateral_rules",
]

"""Collateral subsystem — property eligibility, warrantability, flood zone,
and appraisal gap analysis."""
from .property_eligibility_resolver import (
    FANNIE_INELIGIBLE_TYPES,
    FANNIE_SPECIAL_TYPES,
    FLOOD_ZONE_RULES,
    PropertyEligibilityResolver,
    PropertyEligibilityResult,
)

__all__ = [
    "PropertyEligibilityResolver",
    "PropertyEligibilityResult",
    "FANNIE_INELIGIBLE_TYPES",
    "FANNIE_SPECIAL_TYPES",
    "FLOOD_ZONE_RULES",
]

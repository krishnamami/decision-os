"""Income subsystem — rental income resolution (Schedule E), with more income
streams (self-employed, bonus/overtime, part-time) to follow. INC-A adds the
income entity model (income_sources / employment_history) + aggregator."""
from .income_aggregator import (
    BORROWER_ROLES,
    DEFAULT_QUALIFYING_ROLES,
    INCOME_TYPES,
    get_employment_gaps,
    get_qualifying_income,
)
from .rental_income_resolver import RentalIncomeResolver, add_rental_to_qualifying
from .self_employed_resolver import SelfEmployedResolver

__all__ = [
    "RentalIncomeResolver",
    "add_rental_to_qualifying",
    "SelfEmployedResolver",
    "INCOME_TYPES",
    "BORROWER_ROLES",
    "DEFAULT_QUALIFYING_ROLES",
    "get_qualifying_income",
    "get_employment_gaps",
]

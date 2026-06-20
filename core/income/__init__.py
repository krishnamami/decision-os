"""Income subsystem — rental income resolution (Schedule E), with more income
streams (self-employed, bonus/overtime, part-time) to follow."""
from .rental_income_resolver import RentalIncomeResolver, add_rental_to_qualifying

__all__ = ["RentalIncomeResolver", "add_rental_to_qualifying"]

"""Conditions subsystem — turns resolver-generated condition dicts into live,
trackable condition instances (loan_condition_instances) with SLA, assignment,
and a satisfy/clear lifecycle."""
from .condition_engine import ConditionEngine

__all__ = ["ConditionEngine"]

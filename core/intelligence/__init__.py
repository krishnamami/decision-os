"""Accord intelligence — read-only pipeline analytics that reason OVER the
recorded decisions without re-running the engine.

`change_impact_simulator` (CI-A) answers "what if we moved this overlay rule?"
by re-evaluating a single gate against entity_states and re-reducing the already
-recorded upstream persona outcomes. It NEVER writes the catalogue or decisions
(read-only, like core/audit/reports). Full 14-persona dry-run re-evaluation is a
later slice (CI-B).
"""
from __future__ import annotations

from .change_impact_simulator import (
    SIMULATABLE_FIELDS,
    ChangeImpactSimulator,
    simulate_credit_floor_change,
    simulate_dti_change,
    simulate_ltv_change,
)

__all__ = [
    "SIMULATABLE_FIELDS",
    "ChangeImpactSimulator",
    "simulate_credit_floor_change",
    "simulate_dti_change",
    "simulate_ltv_change",
]

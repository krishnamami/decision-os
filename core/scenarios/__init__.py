"""core/scenarios — the canonical scenario library (SC-B).

`Scenario` / `ScenarioCondition` (base.py) are the typed scenario object; the 16
meridian scenarios (meridian.py) are the single source of truth that replaces the
loose EXPECTED_OUTCOMES + SCENARIO_NOTES dicts. Read-only data definitions — no DB
access, no engine calls. SC-C will migrate the eval to consume this library.
"""
from __future__ import annotations

from core.scenarios.base import Scenario, ScenarioCondition
from core.scenarios.meridian import (
    BEST_DEMO_SCENARIOS,
    CREDIT_FLOOR,
    DTI_MAX,
    LTV_MAX,
    MERIDIAN_BY_APP,
    MERIDIAN_BY_ID,
    MERIDIAN_SCENARIOS,
)
from core.scenarios.runner import ScenarioRunner

__all__ = [
    "Scenario",
    "ScenarioCondition",
    "MERIDIAN_SCENARIOS",
    "MERIDIAN_BY_ID",
    "MERIDIAN_BY_APP",
    "BEST_DEMO_SCENARIOS",
    "CREDIT_FLOOR",
    "DTI_MAX",
    "LTV_MAX",
    "ScenarioRunner",
]

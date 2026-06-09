"""MiroFish — multi-agent swarm simulation engine for Accord.

12 AI personas don't just check thresholds — they DEBATE one loan,
SIMULATE portfolio-wide policy changes, and SWARM the book for emergent
patterns. This package exposes the three engines and their typed models.
"""

from core.mirofish.debate import DebateEngine
from core.mirofish.simulator import PolicySimulator
from core.mirofish.swarm import SwarmAnalyzer
from core.mirofish.scenarios import (
    PREBUILT_SCENARIOS,
    get_scenario,
    list_scenarios,
)
from core.mirofish.models import *  # noqa: F401,F403 — re-export all models

__all__ = [
    "DebateEngine",
    "PolicySimulator",
    "SwarmAnalyzer",
    "PREBUILT_SCENARIOS",
    "get_scenario",
    "list_scenarios",
    "AgentPosition",
    "DebateRound",
    "DebateResult",
    "SimulationScenario",
    "SimulationFlip",
    "SimulationResult",
    "SwarmInsight",
    "SwarmResult",
]

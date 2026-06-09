"""MiroFish — data models for the multi-agent simulation engine.

MiroFish is a *swarm* layer over the 12 lending decision agents. Instead
of each agent independently checking thresholds, MiroFish has them:

  • DEBATE     — N rounds where agents argue about ONE loan, read each
                 other's positions, share signals, and converge (or
                 deadlock). See the Debate* models.
  • SIMULATE   — re-evaluate a whole portfolio under a hypothetical
                 change (policy / stress / regulatory) and surface which
                 decisions FLIP and WHY. See the Simulation* models.
  • SWARM      — agents scan the entire portfolio together to surface
                 EMERGENT patterns (concentration, correlation, anomaly)
                 no single-loan view can see. See the Swarm* models.

These are the typed artefacts the three engines (``DebateEngine``,
``PolicySimulator``, ``SwarmAnalyzer``) produce. Conventions match the
rest of ``core`` (Pydantic v2, ``Field(default_factory=…)`` for ids /
timestamps / containers).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────────────────
# Debate models — 12 agents argue about ONE loan across several rounds.
# ─────────────────────────────────────────────────────────────────────


class AgentPosition(BaseModel):
    """One agent's stance on the loan in a single debate round.

    A position is not just a verdict: it carries the reasoning, the
    signals the agent leaned on, which peers swayed it, and whether it
    moved from the previous round — so the debate transcript is fully
    explainable."""

    agent_id: str                        # e.g. "credit_assessment"
    agent_name: str                      # e.g. "Credit Underwriter"
    round: int                           # 1, 2, or 3
    position: str                        # "allow" | "recommend" | "escalate" | "block"
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str                       # plain-English explanation
    key_signals: list[dict[str, Any]] = Field(default_factory=list)  # [{signal, value, assessment}]
    responding_to: Optional[list[str]] = None  # peer agent_ids that influenced this position
    changed_from: Optional[str] = None   # prior-round position if it changed


class DebateRound(BaseModel):
    """All agent positions for one round, plus what the round surfaced."""

    round_number: int
    positions: list[AgentPosition] = Field(default_factory=list)
    new_signals_shared: list[str] = Field(default_factory=list)  # signals discovered this round
    consensus_reached: bool = False


class DebateResult(BaseModel):
    """The full transcript + outcome of a multi-round debate on one loan."""

    debate_id: UUID = Field(default_factory=uuid4)
    application_id: str
    question: str                        # "Should this loan be approved?"
    rounds: list[DebateRound] = Field(default_factory=list)
    final_consensus: str                 # "allow" | "block" | "deadlock"
    consensus_count: dict[str, int] = Field(default_factory=dict)  # {"allow": 8, "block": 3, ...}
    dissenting_agents: list[str] = Field(default_factory=list)     # agents against the majority
    recommendation: str                  # plain-English final recommendation
    emergent_insights: list[str] = Field(default_factory=list)     # only visible from the multi-agent view
    total_duration_seconds: float = 0.0
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ─────────────────────────────────────────────────────────────────────
# Simulation models — re-evaluate a portfolio under a hypothetical change.
# ─────────────────────────────────────────────────────────────────────


class SimulationScenario(BaseModel):
    """A what-if to apply across the portfolio.

    ``overrides`` is an open parameter map (e.g. a tightened DTI cap, a
    credit-score floor shift, a rate shock) interpreted by the engine."""

    scenario_id: UUID = Field(default_factory=uuid4)
    name: str
    type: Literal["policy", "stress", "regulatory"]
    description: str
    overrides: dict[str, Any] = Field(default_factory=dict)
    tenant_id: str = "default"


class SimulationFlip(BaseModel):
    """One decision that changed outcome under the scenario — with the
    agent's reason, not just the arithmetic."""

    application_id: str
    borrower_name: str
    decision_id: str
    from_outcome: str
    to_outcome: str
    reason: str                          # WHY it flipped (agent reasoning)
    loan_amount: float


class SimulationResult(BaseModel):
    """Portfolio-level outcome of running one scenario."""

    simulation_id: UUID = Field(default_factory=uuid4)
    scenario: SimulationScenario
    status: str
    total_apps: int = 0
    affected_apps: int = 0
    flipped: list[SimulationFlip] = Field(default_factory=list)
    impact: dict[str, Any] = Field(default_factory=dict)  # volume_change, approval_rate delta, …
    agent_insights: list[str] = Field(default_factory=list)  # cross-agent observations
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None


# ─────────────────────────────────────────────────────────────────────
# Swarm models — agents scan the whole portfolio for emergent patterns.
# ─────────────────────────────────────────────────────────────────────


class SwarmInsight(BaseModel):
    """An emergent finding surfaced by one or more agents scanning the
    portfolio together — the kind of pattern no single-loan review sees."""

    insight_type: str                    # "concentration" | "pattern" | "correlation" | "anomaly"
    severity: str                        # "info" | "warning" | "critical"
    detected_by: list[str] = Field(default_factory=list)  # agent_ids that detected it
    description: str                     # plain English
    affected_apps: list[str] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)  # supporting data points


class SwarmResult(BaseModel):
    """The portfolio-wide swarm scan: emergent insights + each agent's
    own portfolio-level summary."""

    swarm_id: UUID = Field(default_factory=uuid4)
    tenant_id: str = "default"
    total_apps_scanned: int = 0
    insights: list[SwarmInsight] = Field(default_factory=list)
    agent_summaries: dict[str, str] = Field(default_factory=dict)  # agent_id -> summary
    created_at: datetime = Field(default_factory=datetime.utcnow)


__all__ = [
    "AgentPosition",
    "DebateRound",
    "DebateResult",
    "SimulationScenario",
    "SimulationFlip",
    "SimulationResult",
    "SwarmInsight",
    "SwarmResult",
]

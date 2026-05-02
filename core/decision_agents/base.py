from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from pydantic import BaseModel, Field

from core.context_store import ContextBundle
from core.normalizer.models import DecisionOutcome
from core.policy_engine import PolicyDecision
from core.trace import WorkJournalEntry


class DecisionAgentError(RuntimeError):
    """Raised when an agent's reasoning is structurally invalid.

    Things like an empty WorkJournalEntry, an out-of-range confidence,
    or a proposed outcome the agent cannot justify. Distinct from
    NormalizationError (event-level) and ConnectorError (source-level)
    so the orchestrator can decide how to handle each."""


class AgentReasoning(BaseModel):
    """The structured payload an agent returns from reason().

    The LLM is responsible for the journal + a proposed outcome +
    confidence. The atomic_tool layer enforces every other invariant
    (policy boundaries, hard rules, critic review, mode routing) — see
    AtomicTool. The LLM cannot bypass any of those steps because it
    only ever sees the AtomicTool's single entry point."""

    journal: WorkJournalEntry
    proposed_outcome: DecisionOutcome
    confidence: float = Field(ge=0.0, le=1.0)
    output_payload: dict[str, Any] = Field(default_factory=dict)


class DecisionAgent(ABC):
    """Base class for one decision in decisions.yaml.

    A subclass per persona (lead_qualification_agent,
    income_verification_agent, ...) implements reason(). Everything
    else — context, policy, critic, trace, routing — is owned by the
    AtomicTool. Subclasses MUST NOT touch the context store, the
    policy engine, the trace writer, or the human queue directly.
    The atomic-tool contract is the only governed entry point."""

    def __init__(
        self,
        agent_id: str,
        persona: str,
        decision_id: str,
    ):
        if not agent_id:
            raise ValueError("agent_id is required (no_agent_without_permissions)")
        if not persona:
            raise ValueError("persona is required")
        if not decision_id:
            raise ValueError("decision_id is required")
        self._agent_id = agent_id
        self._persona = persona
        self._decision_id = decision_id

    @property
    def agent_id(self) -> str:
        return self._agent_id

    @property
    def persona(self) -> str:
        return self._persona

    @property
    def decision_id(self) -> str:
        return self._decision_id

    @abstractmethod
    async def reason(
        self,
        bundle: ContextBundle,
        policy: Optional[PolicyDecision] = None,
    ) -> AgentReasoning:
        """Produce a WorkJournalEntry, proposed outcome, and confidence
        from the supplied bundle.

        ``policy`` is the pre-reasoning hard-rule check from the policy
        engine. If a hard rule has already blocked the decision,
        subclasses can use it to explain *why* in the journal; they
        cannot override the eventual block — the atomic_tool re-runs
        the policy engine after reasoning and a hard block always wins."""

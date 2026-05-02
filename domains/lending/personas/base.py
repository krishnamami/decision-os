from __future__ import annotations

import json
import os
from typing import Any, Optional

from core.context_store import ContextBundle
from core.decision_agents import AgentReasoning, DecisionAgent
from core.normalizer.models import DecisionOutcome
from core.policy_engine import PolicyDecision
from core.trace import Contradiction, Signal, SignalDirection, WorkJournalEntry


# ─────────────────────────────────────────────────────────────────────
# LendingPersona — shared base for the 12 lending decision agents.
#
# Each subclass keeps its own deterministic, rules-based reasoning path
# (`_compute_offline`) so smoke tests, seed-event replays, and the
# scheduled real-backend verification all run without an Anthropic API
# key. The same subclass can opt into an Anthropic-driven path via
# ``use_anthropic=True`` — when that is set the LLM produces the
# WorkJournalEntry given the bundle + policy + boundary clauses, and
# the offline computation supplies the canonical output_payload values
# the policy engine needs to evaluate the boundary.
#
# Rationale for the split: the policy engine has the last word on
# outcome (no_action_without_policy). The agent's job is to compute the
# domain values (dti, ltv, intent_score, fraud_score, ...) and to
# explain its reasoning in a journal the critic can audit. Offline
# code already computes the values; the LLM's contribution is the
# WorkJournalEntry's narrative — hypothesis, signals, contradictions,
# confidence basis. Both paths produce the same AgentReasoning shape so
# AtomicTool doesn't care which one ran.
# ─────────────────────────────────────────────────────────────────────


# Anthropic prompt-cache TTL — the system prompt + decisions.yaml boundary
# text are cache-stable across thousands of decisions.
_ANTHROPIC_DEFAULT_MODEL = "claude-sonnet-4-6"


class LendingPersona(DecisionAgent):
    """Base class for the 12 lending decision agents.

    Subclasses implement:
      - `_compute_offline(bundle)` — pulls signals from the bundle and
        upstream outputs, returns a tuple of (output_payload,
        proposed_outcome, confidence, signals, contradictions, summary,
        confidence_basis, hypothesis).
      - Optionally override `_system_prompt()` if the default isn't
        enough for the LLM path.
    """

    def __init__(
        self,
        agent_id: str,
        persona: str,
        decision_id: str,
        *,
        use_anthropic: bool = False,
        anthropic_model: str = _ANTHROPIC_DEFAULT_MODEL,
        anthropic_client: Optional[Any] = None,
    ):
        super().__init__(agent_id, persona, decision_id)
        self._use_anthropic = bool(use_anthropic)
        self._anthropic_model = anthropic_model
        self._anthropic_client = anthropic_client

    @property
    def use_anthropic(self) -> bool:
        return self._use_anthropic

    # ── DecisionAgent contract ───────────────────────────────────────

    async def reason(
        self,
        bundle: ContextBundle,
        policy: Optional[PolicyDecision] = None,
    ) -> AgentReasoning:
        offline = self._compute_offline(bundle, policy)

        if not self._use_anthropic:
            return self._build_reasoning(offline)

        narrative = await self._reason_anthropic(bundle, policy, offline)
        return self._build_reasoning(offline, narrative_override=narrative)

    # ── Subclass extension points ────────────────────────────────────

    def _compute_offline(
        self,
        bundle: ContextBundle,
        policy: Optional[PolicyDecision],
    ) -> "OfflineReasoning":
        raise NotImplementedError(
            f"{type(self).__name__} must implement _compute_offline()"
        )

    def _system_prompt(self) -> str:
        return (
            "You are the {persona} for the lending decision {decision_id}. "
            "Read the bundle and the upstream outputs, then return a JSON "
            "object with hypothesis_tested, signals_evaluated, "
            "contradictions_found, conclusion, confidence_basis, and "
            "human_readable_summary. Do not invent fields outside the "
            "bundle. Stay within your boundary clauses."
        ).format(persona=self.persona, decision_id=self.decision_id)

    # ── Anthropic call — opt-in only ─────────────────────────────────

    async def _reason_anthropic(
        self,
        bundle: ContextBundle,
        policy: Optional[PolicyDecision],
        offline: "OfflineReasoning",
    ) -> Optional[WorkJournalEntry]:
        client = self._anthropic_client or self._lazy_client()
        if client is None:
            # No SDK / no API key — fall back to offline narrative.
            return None

        system = self._system_prompt()
        user = self._build_user_prompt(bundle, policy, offline)

        # Cache the system prompt — it's invariant across thousands of
        # decisions for the same persona, so cache_control on the system
        # block keeps cost down dramatically.
        try:
            response = await client.messages.create(
                model=self._anthropic_model,
                max_tokens=1024,
                system=[
                    {
                        "type": "text",
                        "text": system,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": user}],
            )
        except Exception:
            return None

        text = _extract_text(response)
        if not text:
            return None
        try:
            return _journal_from_json(text, fallback=offline)
        except Exception:
            return None

    @staticmethod
    def _build_user_prompt(
        bundle: ContextBundle,
        policy: Optional[PolicyDecision],
        offline: "OfflineReasoning",
    ) -> str:
        payload = {
            "decision_id": bundle.decision_id,
            "application_id": bundle.application_id,
            "context_window_days": bundle.context_window_days,
            "objects": bundle.objects,
            "upstream_outputs": bundle.upstream_outputs,
            "computed_values": offline.output_payload,
            "policy_pre_check": (
                {
                    "outcome": policy.outcome.value,
                    "matched_clause": policy.matched_clause,
                    "reasons": list(policy.reasons),
                }
                if policy
                else None
            ),
            "instructions": (
                "Return JSON with keys: hypothesis_tested (str), "
                "signals_evaluated (list of {name, value, weight, "
                "direction in [supports, contradicts, neutral]}), "
                "contradictions_found (list of {signal_a, signal_b, "
                "description, resolved}), conclusion (str), "
                "confidence_basis (str), human_readable_summary (str). "
                "Stay grounded in the bundle's signals."
            ),
        }
        return json.dumps(payload, default=str)

    # ── Anthropic SDK lazy import ────────────────────────────────────

    @staticmethod
    def _lazy_client() -> Optional[Any]:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return None
        try:
            from anthropic import AsyncAnthropic  # type: ignore
        except ImportError:
            return None
        return AsyncAnthropic()

    # ── Reasoning assembly ───────────────────────────────────────────

    def _build_reasoning(
        self,
        offline: "OfflineReasoning",
        *,
        narrative_override: Optional[WorkJournalEntry] = None,
    ) -> AgentReasoning:
        if narrative_override is not None:
            journal = narrative_override
        else:
            journal = WorkJournalEntry(
                hypothesis_tested=offline.hypothesis,
                signals_evaluated=offline.signals,
                contradictions_found=offline.contradictions,
                conclusion=offline.conclusion,
                confidence_basis=offline.confidence_basis,
                human_readable_summary=offline.summary,
            )
        return AgentReasoning(
            journal=journal,
            proposed_outcome=offline.proposed_outcome,
            confidence=offline.confidence,
            output_payload=offline.output_payload,
        )


# ─────────────────────────────────────────────────────────────────────
# OfflineReasoning — the structured output of `_compute_offline`.
# ─────────────────────────────────────────────────────────────────────


class OfflineReasoning:
    """Container for the offline reasoning path's output.

    Plain class (not Pydantic) because subclasses construct it on the
    hot path of every decision and we keep the surface dirt-cheap."""

    __slots__ = (
        "output_payload",
        "proposed_outcome",
        "confidence",
        "signals",
        "contradictions",
        "summary",
        "confidence_basis",
        "hypothesis",
        "conclusion",
    )

    def __init__(
        self,
        *,
        output_payload: dict[str, Any],
        proposed_outcome: DecisionOutcome,
        confidence: float,
        signals: list[Signal],
        contradictions: list[Contradiction],
        hypothesis: str,
        conclusion: str,
        confidence_basis: str,
        summary: str,
    ):
        self.output_payload = output_payload
        self.proposed_outcome = proposed_outcome
        self.confidence = max(0.0, min(1.0, confidence))
        self.signals = signals
        self.contradictions = contradictions
        self.hypothesis = hypothesis
        self.conclusion = conclusion
        self.confidence_basis = confidence_basis
        self.summary = summary


# ─────────────────────────────────────────────────────────────────────
# Bundle helpers — all 12 personas reach into bundle.objects /
# upstream_outputs the same way.
# ─────────────────────────────────────────────────────────────────────


def first_object(
    bundle: ContextBundle, object_type_id: str
) -> Optional[dict[str, Any]]:
    entities = bundle.objects.get(object_type_id) or {}
    if not entities:
        return None
    # Return the first entity. Order is dict-insertion (Python 3.7+).
    for value in entities.values():
        return value
    return None


def latest_object(
    bundle: ContextBundle, object_type_id: str, *, sort_by: str = "verified_at"
) -> Optional[dict[str, Any]]:
    entities = bundle.objects.get(object_type_id) or {}
    if not entities:
        return None
    rows = list(entities.values())
    rows.sort(key=lambda v: str(v.get(sort_by) or ""), reverse=True)
    return rows[0]


def upstream_payload(
    bundle: ContextBundle, decision_id: str
) -> dict[str, Any]:
    out = bundle.upstream_outputs.get(decision_id) or {}
    payload = out.get("payload") if isinstance(out, dict) else None
    return payload if isinstance(payload, dict) else {}


def make_signal(
    name: str,
    value: Any,
    *,
    direction: SignalDirection = SignalDirection.NEUTRAL,
    weight: float = 1.0,
    source: Optional[str] = None,
    notes: Optional[str] = None,
) -> Signal:
    return Signal(
        name=name,
        value=value,
        direction=direction,
        weight=weight,
        source=source,
        notes=notes,
    )


# ─────────────────────────────────────────────────────────────────────
# Anthropic response helpers
# ─────────────────────────────────────────────────────────────────────


def _extract_text(response: Any) -> str:
    content = getattr(response, "content", None)
    if not content:
        return ""
    if isinstance(content, list):
        parts = []
        for block in content:
            text = getattr(block, "text", None)
            if text:
                parts.append(text)
        return "\n".join(parts)
    return str(content)


def _journal_from_json(
    text: str, *, fallback: OfflineReasoning
) -> WorkJournalEntry:
    payload = json.loads(text)
    signals_raw = payload.get("signals_evaluated") or []
    contradictions_raw = payload.get("contradictions_found") or []
    return WorkJournalEntry(
        hypothesis_tested=str(payload.get("hypothesis_tested") or fallback.hypothesis),
        signals_evaluated=[Signal(**s) for s in signals_raw if isinstance(s, dict)],
        contradictions_found=[
            Contradiction(**c) for c in contradictions_raw if isinstance(c, dict)
        ],
        conclusion=str(payload.get("conclusion") or fallback.conclusion),
        confidence_basis=str(
            payload.get("confidence_basis") or fallback.confidence_basis
        ),
        human_readable_summary=str(
            payload.get("human_readable_summary") or fallback.summary
        ),
    )


__all__ = [
    "LendingPersona",
    "OfflineReasoning",
    "first_object",
    "latest_object",
    "make_signal",
    "upstream_payload",
]

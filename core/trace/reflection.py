from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable, Optional, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from core.normalizer.models import DecisionOutcome

from .trace_schema import DecisionTrace, HumanReview


# ─────────────────────────────────────────────────────────────────────
# Reflection — capture human overrides, replay to same agent.
#
# decisions.yaml `reflection:` block defines:
#
#   trigger:        human_override
#   extract:        [override_reason, override_reason_code,
#                    reviewer_role, original_ai_decision]
#   store_as:       agent_learning
#   feed_back_to:   same_agent_next_similar_event
#   retention_days: 365
#
# This module owns the runtime side of that contract:
#
#   1. capture(trace, review) — turns a human override on a finished
#      DecisionTrace into an AgentLearning record.
#   2. recall(agent_id, decision_id, similarity_tags) — pulls relevant
#      lessons for the next similar event so the agent can read them.
#   3. retention pruning — recall() honours the retention window so a
#      lesson stops feeding back after 365 days without ever rewriting
#      history.
#
# AgentLearnings live on a separate store from DecisionTrace because
# they are the *consequences* of overrides, not the trace itself —
# traces remain append-only and immutable. Linking back to the trace is
# done via `trace_id`.
# ─────────────────────────────────────────────────────────────────────


# Default retention from decisions.yaml. Held here as the floor, but the
# value the runtime actually uses is read from DecisionsSpec.reflection
# at startup.
DEFAULT_RETENTION_DAYS = 365


class AgentLearning(BaseModel):
    """One captured human override, retained as a per-agent lesson.

    The fields mirror knowledge_base.json `system_object_types.AgentLearning`
    so the YAML, the JSON ontology, and the runtime model agree.

    similarity_tags is the set of strings the recall() lookup matches
    against. Tags are produced by the caller (the API override route or
    the atomic_tool) — typically (override_reason_code, reviewer_role,
    decision_id, plus any domain-specific markers from the trace's
    output_payload like ``employment_type:self_employed`` or
    ``credit_band:near_prime``)."""

    agent_learning_id: UUID = Field(default_factory=uuid4)
    agent_id: str
    persona: str
    decision_id: str
    trace_id: UUID

    original_ai_decision: DecisionOutcome
    human_decision: DecisionOutcome

    override_reason: str
    override_reason_code: Optional[str] = None
    reviewer_role: str
    reviewer_id: Optional[str] = None

    lesson: str
    similarity_tags: list[str] = Field(default_factory=list)

    captured_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: datetime

    @property
    def is_active(self) -> bool:
        return datetime.utcnow() <= self.expires_at


# ─────────────────────────────────────────────────────────────────────
# Storage
# ─────────────────────────────────────────────────────────────────────


class LearningStore(Protocol):
    """Persistence surface for AgentLearning records.

    Production swap is Postgres-backed; the in-memory implementation
    below exercises the contract for tests."""

    async def write(self, learning: AgentLearning) -> UUID: ...
    async def get(self, learning_id: UUID) -> Optional[AgentLearning]: ...
    async def list_for_agent(
        self,
        agent_id: str,
        decision_id: Optional[str] = None,
    ) -> list[AgentLearning]: ...
    async def list_for_decision(
        self, decision_id: str
    ) -> list[AgentLearning]: ...


class InMemoryLearningStore:
    """Reference implementation. Append-only — overwriting an existing
    learning_id is a programming error."""

    def __init__(self) -> None:
        self._learnings: dict[UUID, AgentLearning] = {}

    async def write(self, learning: AgentLearning) -> UUID:
        if learning.agent_learning_id in self._learnings:
            raise ValueError(
                f"agent_learning_id {learning.agent_learning_id} already written"
            )
        self._learnings[learning.agent_learning_id] = learning
        return learning.agent_learning_id

    async def get(self, learning_id: UUID) -> Optional[AgentLearning]:
        return self._learnings.get(learning_id)

    async def list_for_agent(
        self,
        agent_id: str,
        decision_id: Optional[str] = None,
    ) -> list[AgentLearning]:
        return [
            lrn for lrn in self._learnings.values()
            if lrn.agent_id == agent_id
            and (decision_id is None or lrn.decision_id == decision_id)
        ]

    async def list_for_decision(
        self, decision_id: str
    ) -> list[AgentLearning]:
        return [
            lrn for lrn in self._learnings.values()
            if lrn.decision_id == decision_id
        ]

    def __len__(self) -> int:
        return len(self._learnings)


# ─────────────────────────────────────────────────────────────────────
# ReflectionService
# ─────────────────────────────────────────────────────────────────────


class ReflectionService:
    """Captures human overrides and recalls relevant past lessons.

    Construct with a LearningStore and the retention window. Both
    capture() and recall() are async so a real persistent store is
    drop-in."""

    def __init__(
        self,
        store: LearningStore,
        *,
        retention_days: int = DEFAULT_RETENTION_DAYS,
    ):
        if retention_days <= 0:
            raise ValueError("retention_days must be > 0")
        self._store = store
        self._retention_days = retention_days

    @property
    def retention_days(self) -> int:
        return self._retention_days

    @property
    def store(self) -> LearningStore:
        return self._store

    # ── Capture ──────────────────────────────────────────────────────

    async def capture(
        self,
        trace: DecisionTrace,
        review: HumanReview,
        *,
        similarity_tags: Optional[Iterable[str]] = None,
        lesson: Optional[str] = None,
    ) -> AgentLearning:
        """Turn a human override into a stored AgentLearning record.

        No-op if the review is not actually an override (overridden=False
        or original_outcome == final_outcome) — the reflection block
        triggers on `human_override` only, not on confirmations."""

        if not review.overridden:
            raise ValueError(
                "ReflectionService.capture() requires review.overridden=True; "
                "human approvals without override are not reflection events"
            )
        if review.original_ai_decision == review.final_outcome:
            # A "confirm" stamped as an override would otherwise produce
            # a noise lesson. Refuse the write so the next agent doesn't
            # learn from a non-override.
            raise ValueError(
                "review.original_ai_decision matches final_outcome; not an override"
            )

        tags = list(similarity_tags or [])
        # Always tag with the reviewer_role and override_reason_code so
        # recall() can prefer lessons from the same kind of reviewer.
        if review.reviewer_role and review.reviewer_role not in tags:
            tags.append(review.reviewer_role)
        if review.override_reason_code and review.override_reason_code not in tags:
            tags.append(review.override_reason_code)
        # Decision_id is implicit but we tag it too so list_for_decision
        # is enough for a baseline recall path.
        if trace.decision_id not in tags:
            tags.append(trace.decision_id)

        body = lesson or _summarize_override(trace, review)

        learning = AgentLearning(
            agent_id=trace.agent_id,
            persona=trace.persona,
            decision_id=trace.decision_id,
            trace_id=trace.trace_id,
            original_ai_decision=review.original_ai_decision,
            human_decision=review.final_outcome,
            override_reason=review.override_reason or "",
            override_reason_code=review.override_reason_code,
            reviewer_role=review.reviewer_role,
            reviewer_id=review.reviewer_id,
            lesson=body,
            similarity_tags=tags,
            expires_at=datetime.utcnow() + timedelta(days=self._retention_days),
        )

        await self._store.write(learning)
        return learning

    # ── Recall ───────────────────────────────────────────────────────

    async def recall(
        self,
        agent_id: str,
        decision_id: str,
        *,
        similarity_tags: Optional[Iterable[str]] = None,
        limit: int = 5,
    ) -> list[AgentLearning]:
        """Fetch lessons to feed back to ``agent_id`` for ``decision_id``.

        Lessons are ranked by tag overlap, then by recency. Expired
        records are filtered out — retention is honoured at recall
        time, never by destructive deletes."""

        candidates = await self._store.list_for_agent(agent_id, decision_id)
        active = [lrn for lrn in candidates if lrn.is_active]
        if not active:
            return []

        wanted = set(similarity_tags or ())
        wanted.add(decision_id)  # at minimum match on the decision

        def rank(lrn: AgentLearning) -> tuple[int, datetime]:
            overlap = len(wanted & set(lrn.similarity_tags))
            return (overlap, lrn.captured_at)

        active.sort(key=rank, reverse=True)
        return active[:limit]

    async def prune_expired(self) -> int:
        """Best-effort prune of expired records.

        Production deployments should run this periodically; recall()
        already filters expired lessons so pruning is purely a
        housekeeping concern. The in-memory store grows unbounded
        without it."""

        store = self._store
        # Only InMemoryLearningStore exposes the internal dict; for the
        # protocol surface we just no-op. Postgres swap will implement
        # this directly in SQL.
        if isinstance(store, InMemoryLearningStore):
            now = datetime.utcnow()
            expired = [
                lid for lid, lrn in store._learnings.items()  # noqa: SLF001
                if lrn.expires_at < now
            ]
            for lid in expired:
                store._learnings.pop(lid, None)  # noqa: SLF001
            return len(expired)
        return 0


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────


def _summarize_override(trace: DecisionTrace, review: HumanReview) -> str:
    """Plain-language summary the next agent will read.

    Kept short and structured — the agent sees this verbatim alongside
    its bundle, so the format must be parseable by the LLM but also
    readable by a human flipping through the agent's lesson log."""

    lines = [
        f"On a previous {trace.decision_id} decision the AI proposed "
        f"{review.original_ai_decision.value!r} with confidence {trace.confidence:.2f}.",
        f"The {review.reviewer_role} reviewer overrode it to "
        f"{review.final_outcome.value!r}.",
    ]
    if review.override_reason:
        lines.append(f"Reason: {review.override_reason}")
    if review.override_reason_code:
        lines.append(f"Reason code: {review.override_reason_code}")
    lines.append(
        "Next time the same agent sees a similar event, weight that override "
        "into the journal's `signals_evaluated` and `confidence_basis`."
    )
    return " ".join(lines)


def derive_similarity_tags(trace: DecisionTrace) -> list[str]:
    """Cheap default tag extraction from a trace.

    Pulls a few well-known fields out of `output_payload` so the API
    layer doesn't need a per-decision tag function. Subclasses /
    domain packs can replace this with a richer extractor."""

    tags: list[str] = [trace.decision_id, trace.persona]
    payload = trace.output_payload or {}
    for key in ("employment_type", "credit_band", "loan_purpose", "loan_type"):
        v = payload.get(key)
        if isinstance(v, str) and v:
            tags.append(f"{key}:{v}")
    return tags


__all__ = [
    "AgentLearning",
    "DEFAULT_RETENTION_DAYS",
    "InMemoryLearningStore",
    "LearningStore",
    "ReflectionService",
    "derive_similarity_tags",
]

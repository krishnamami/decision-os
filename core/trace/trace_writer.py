from __future__ import annotations

from typing import Optional, Protocol
from uuid import UUID

from .trace_schema import DecisionTrace, HumanReview


class TraceWriter(Protocol):
    """Append-only trace persistence.

    The atomic_tool calls write() exactly once per decision execution.
    Production swaps this for a Postgres-backed writer; the in-memory
    variant exercises the contract in tests and seeds the upcoming
    reflection / outcome-tracker work.

    `attach_human_review` is the one allowed mutation: a HumanReview
    arrives later, after the agent's trace is already on disk. The
    trace's identity (trace_id, reasoning, policy outcome, original
    confidence) never changes — only the human_review side-channel is
    set. Postgres swap implements this as either a row update on the
    traces table or an INSERT into a sibling human_reviews table that
    get() joins on read; both satisfy the contract."""

    async def write(self, trace: DecisionTrace) -> UUID: ...
    async def get(self, trace_id: UUID) -> Optional[DecisionTrace]: ...
    async def list_for_application(
        self, application_id: str
    ) -> list[DecisionTrace]: ...
    async def attach_human_review(
        self, trace_id: UUID, review: HumanReview
    ) -> Optional[DecisionTrace]: ...


class InMemoryTraceWriter:
    """Reference implementation. Swap for the Postgres writer in
    production — append-only is the only invariant the contract
    requires."""

    def __init__(self) -> None:
        self._traces: dict[UUID, DecisionTrace] = {}

    async def write(self, trace: DecisionTrace) -> UUID:
        if trace.trace_id in self._traces:
            raise ValueError(
                f"trace_id {trace.trace_id} already written; traces are append-only"
            )
        self._traces[trace.trace_id] = trace
        return trace.trace_id

    async def get(self, trace_id: UUID) -> Optional[DecisionTrace]:
        return self._traces.get(trace_id)

    async def list_for_application(
        self, application_id: str
    ) -> list[DecisionTrace]:
        return [
            t for t in self._traces.values()
            if t.application_id == application_id
        ]

    async def attach_human_review(
        self, trace_id: UUID, review: HumanReview
    ) -> Optional[DecisionTrace]:
        existing = self._traces.get(trace_id)
        if existing is None:
            return None
        updated = existing.model_copy(update={"human_review": review})
        self._traces[trace_id] = updated
        return updated

    def __len__(self) -> int:
        return len(self._traces)

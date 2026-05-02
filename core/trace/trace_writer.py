from __future__ import annotations

from typing import Optional, Protocol
from uuid import UUID

from .trace_schema import DecisionTrace


class TraceWriter(Protocol):
    """Append-only trace persistence.

    The atomic_tool calls write() exactly once per decision execution.
    Production swaps this for a Postgres-backed writer; the in-memory
    variant exercises the contract in tests and seeds the upcoming
    reflection / outcome-tracker work."""

    async def write(self, trace: DecisionTrace) -> UUID: ...
    async def get(self, trace_id: UUID) -> Optional[DecisionTrace]: ...
    async def list_for_application(
        self, application_id: str
    ) -> list[DecisionTrace]: ...


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

    def __len__(self) -> int:
        return len(self._traces)

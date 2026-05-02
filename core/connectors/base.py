from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from datetime import datetime
from enum import Enum
from typing import Any, AsyncIterator, Awaitable, Callable, Optional, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from core.normalizer.models import BaseEvent, NormalizationError, normalize_event


# ─────────────────────────────────────────────────────────────────────
# Errors + sink protocol
# ─────────────────────────────────────────────────────────────────────


class ConnectorError(RuntimeError):
    """Adapter-level failure — bad fixture, network, parse, etc.

    Distinct from NormalizationError, which is raised by
    normalize_event when the canonical event cannot be built."""


class ConnectorHealth(str, Enum):
    UNINITIALIZED = "uninitialized"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILED = "failed"
    STOPPED = "stopped"


class EventSink(Protocol):
    """Where the connector hands canonical BaseEvents to the rest of the
    pipeline. The downstream layer (event bus, ingest API, dead-letter
    store) supplies the implementation."""

    async def __call__(self, event: BaseEvent) -> None: ...


# ─────────────────────────────────────────────────────────────────────
# BaseConnector
#
# Adapters do source-specific parsing and normalization, then hand the
# typed BaseEvent to the EventSink. Entity hydration (Applicant /
# Application / CreditProfile / etc.) does NOT happen here — the
# normalizer + ontology layers own that.
# ─────────────────────────────────────────────────────────────────────


class BaseConnector(ABC):
    """Common surface for push and pull connectors.

    The contract every adapter satisfies:
      - parse_raw(raw_payload)  → canonical dict for normalize_event
      - emit(raw_payload, ...)   → BaseEvent + hand to sink
      - health                   → operational status for observability

    Adapters MUST NOT touch the context store, policy engine, or trace
    layer. Their only job is "source bytes → canonical BaseEvent →
    sink". A misbehaving adapter cannot corrupt the rest of the
    pipeline because it can only emit through normalize_event(), which
    enforces strict pydantic validation."""

    source_system: str
    source_kind: str  # "push" | "pull"

    def __init__(
        self,
        source_system: str,
        sink: EventSink,
        *,
        clock: Callable[[], datetime] = datetime.utcnow,
    ):
        if not source_system:
            raise ValueError("source_system is required")
        self.source_system = source_system
        self._sink = sink
        self._clock = clock
        self._health: ConnectorHealth = ConnectorHealth.UNINITIALIZED
        self._emitted: int = 0
        self._failed: int = 0

    # ── Health / metrics ─────────────────────────────────────────────

    @property
    def health(self) -> ConnectorHealth:
        return self._health

    @property
    def emitted_count(self) -> int:
        return self._emitted

    @property
    def failed_count(self) -> int:
        return self._failed

    # ── Subclasses implement parse_raw(); everything else is shared ─

    @abstractmethod
    def parse_raw(self, raw: Any) -> dict[str, Any]:
        """Convert a source-specific payload (CSV row, HTTP body, etc.)
        into the canonical dict shape ``normalize_event`` expects.

        MUST set ``event_type`` to a valid EventType. May set
        ``source_system`` (otherwise self.source_system is stamped)."""

    # ── Emit pipeline ─────────────────────────────────────────────────

    async def emit(
        self,
        raw: Any,
        *,
        correlation_id: Optional[UUID] = None,
        request_id: Optional[UUID] = None,
    ) -> BaseEvent:
        """Parse a raw payload, normalize it, hand it to the sink.

        Single canonical entry point — every adapter routes through
        here, and every event the pipeline sees has been validated by
        normalize_event()."""

        try:
            canonical = self.parse_raw(raw)
        except Exception as err:
            self._failed += 1
            self._health = ConnectorHealth.DEGRADED
            raise ConnectorError(
                f"{self.source_system}: parse_raw failed: {err}"
            ) from err

        canonical.setdefault("source_system", self.source_system)
        canonical.setdefault("received_at", self._clock())
        if correlation_id is not None:
            canonical["correlation_id"] = correlation_id
        if request_id is not None:
            canonical["request_id"] = request_id

        try:
            event = normalize_event(canonical)
        except NormalizationError:
            self._failed += 1
            self._health = ConnectorHealth.DEGRADED
            raise

        try:
            await self._sink(event)
        except Exception as err:
            self._failed += 1
            self._health = ConnectorHealth.DEGRADED
            raise ConnectorError(
                f"{self.source_system}: sink rejected event {event.event_id}: {err}"
            ) from err

        self._emitted += 1
        if self._health != ConnectorHealth.STOPPED:
            self._health = ConnectorHealth.HEALTHY
        return event


# ─────────────────────────────────────────────────────────────────────
# PushConnector — source initiates (webhooks, file drops, streams).
# ─────────────────────────────────────────────────────────────────────


class PushConnector(BaseConnector):
    """Connector for sources that push to us.

    Examples: borrower portal webhooks, e-sign callbacks, payroll
    provider webhooks, file drops in S3 / GCS / inbound FTP.

    Subclasses implement an async iterator ``stream()`` that yields raw
    payloads. ``listen()`` drains the stream and pumps each payload
    through ``emit()``. Lifecycle methods are async-friendly — a
    long-running webhook receiver can override them, but the default
    listen() works for batch / replay sources too."""

    source_kind: str = "push"

    def __init__(self, source_system: str, sink: EventSink, **kw: Any):
        super().__init__(source_system, sink, **kw)
        self._stop_event = asyncio.Event()

    @abstractmethod
    def stream(self) -> AsyncIterator[Any]:
        """Async iterator over source-specific raw payloads.

        ``__aiter__`` is enough; the framework owns the loop and the
        adapter is free to source from a webhook queue, an SQS poller,
        a directory watcher, or in-memory fixtures."""

    async def listen(self) -> int:
        """Drain stream() into the sink. Returns the number of events
        emitted in this run.

        Long-running implementations can also call ``stop()`` to break
        out of the loop without cancelling the task."""

        emitted = 0
        async for raw in self.stream():
            if self._stop_event.is_set():
                break
            await self.emit(raw)
            emitted += 1
        if self._health != ConnectorHealth.STOPPED:
            self._health = ConnectorHealth.HEALTHY
        return emitted

    def stop(self) -> None:
        self._stop_event.set()
        self._health = ConnectorHealth.STOPPED


# ─────────────────────────────────────────────────────────────────────
# PullConnector — we initiate (bureau pulls, Plaid, AVMs, TWN).
# ─────────────────────────────────────────────────────────────────────


class PullRequest(BaseModel):
    """Outbound query the pull connector executes against the source.

    Carries an explicit ``request_id`` so the inbound response (and the
    BaseEvent emitted from it) can be paired with the call. The
    correlation_id is whatever upstream identifier the caller wants
    threaded through (application_id, decision_run_id, ...) — it
    survives the round-trip on BaseEvent."""

    request_id: UUID = Field(default_factory=uuid4)
    correlation_id: Optional[UUID] = None
    query: dict[str, Any] = Field(default_factory=dict)
    issued_at: datetime = Field(default_factory=datetime.utcnow)


class PullConnector(BaseConnector):
    """Connector for sources we query.

    Examples: credit bureaus (Experian, TransUnion, Equifax),
    Plaid / Argyle / Pinwheel income, AVM lookups, title search, The
    Work Number.

    Subclasses implement ``_perform(request)`` returning the raw source
    response. The base class wraps it: stamps request_id +
    correlation_id, runs parse_raw + normalize_event, hands the event
    to the sink, increments counters."""

    source_kind: str = "pull"

    def __init__(self, source_system: str, sink: EventSink, **kw: Any):
        super().__init__(source_system, sink, **kw)

    @abstractmethod
    async def _perform(self, request: PullRequest) -> Any:
        """Execute the outbound call. Returns the source-specific raw
        payload that ``parse_raw`` knows how to digest."""

    async def fetch(
        self,
        query: Optional[dict[str, Any]] = None,
        *,
        correlation_id: Optional[UUID] = None,
        request_id: Optional[UUID] = None,
    ) -> BaseEvent:
        """One-shot pull. Builds a PullRequest, executes, emits."""

        request = PullRequest(
            request_id=request_id or uuid4(),
            correlation_id=correlation_id,
            query=query or {},
        )
        try:
            raw = await self._perform(request)
        except Exception as err:
            self._failed += 1
            self._health = ConnectorHealth.DEGRADED
            raise ConnectorError(
                f"{self.source_system}: _perform failed for "
                f"request_id={request.request_id}: {err}"
            ) from err

        return await self.emit(
            raw,
            correlation_id=request.correlation_id,
            request_id=request.request_id,
        )

    async def poll(
        self,
        queries: list[dict[str, Any]],
        *,
        interval_seconds: float = 0.0,
    ) -> list[BaseEvent]:
        """Issue a batch of pull queries. Used for scheduled sweeps —
        e.g. nightly bureau refreshes — and for tests that need to
        deterministically replay a fixture file.

        ``interval_seconds`` lets the caller throttle without spinning
        up an external scheduler."""

        events: list[BaseEvent] = []
        for q in queries:
            event = await self.fetch(q)
            events.append(event)
            if interval_seconds > 0:
                await asyncio.sleep(interval_seconds)
        return events

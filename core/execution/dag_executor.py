from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime
from enum import Enum
from typing import Any, Awaitable, Callable, Optional, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from core.context_store import EntityResolver
from core.decision_agents import (
    AtomicTool,
    AtomicToolResult,
    DecisionAgent,
    RouteAction,
)
from core.normalizer.models import DecisionOutcome
from core.policy_engine import PolicyOutcome, UpstreamSummary


# ─────────────────────────────────────────────────────────────────────
# Errors
# ─────────────────────────────────────────────────────────────────────


class DAGExecutorError(RuntimeError):
    """Raised when the executor cannot continue: cyclic dependency,
    misconfigured execution_order, or unrecoverable wave failure."""


# ─────────────────────────────────────────────────────────────────────
# Event bus
#
# Lightweight pub/sub for record_updated events. The executor publishes
# one event per decision execution; subscribers (observability,
# dependent-decision wakeups in a streaming setup, downstream
# connectors that need to write back to Encompass / borrower portal /
# CRM) can listen.
# ─────────────────────────────────────────────────────────────────────


class ExecutionEventType(str, Enum):
    DECISION_STARTED = "decision_started"
    DECISION_COMPLETED = "decision_completed"
    DECISION_BLOCKED = "decision_blocked"
    DECISION_SKIPPED = "decision_skipped"
    DECISION_FAILED = "decision_failed"
    PIPELINE_HALTED = "pipeline_halted"
    RECORD_UPDATED = "record_updated"


class ExecutionEvent(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    type: ExecutionEventType
    application_id: str
    decision_id: Optional[str] = None
    outcome: Optional[DecisionOutcome] = None
    payload: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime = Field(default_factory=datetime.utcnow)


EventHandler = Callable[[ExecutionEvent], Awaitable[None]]


class EventBus(Protocol):
    async def publish(self, event: ExecutionEvent) -> None: ...
    def subscribe(
        self, type: ExecutionEventType, handler: EventHandler
    ) -> None: ...


class InMemoryEventBus:
    """Reference implementation. Handlers are awaited sequentially on
    publish so a slow subscriber backs up the stream — adequate for
    tests and small batch runs. Production swaps for a real broker
    (Redis Streams, Kafka, NATS) but the protocol is stable."""

    def __init__(self) -> None:
        self._handlers: dict[ExecutionEventType, list[EventHandler]] = defaultdict(list)
        self._history: list[ExecutionEvent] = []

    async def publish(self, event: ExecutionEvent) -> None:
        self._history.append(event)
        for handler in list(self._handlers.get(event.type, ())):
            await handler(event)

    def subscribe(
        self, type: ExecutionEventType, handler: EventHandler
    ) -> None:
        self._handlers[type].append(handler)

    @property
    def history(self) -> list[ExecutionEvent]:
        return list(self._history)


# ─────────────────────────────────────────────────────────────────────
# Result
# ─────────────────────────────────────────────────────────────────────


class ExecutionResult(BaseModel):
    application_id: str
    started_at: datetime
    ended_at: datetime
    duration_ms: int
    completed_decisions: list[str] = Field(default_factory=list)
    skipped_decisions: list[str] = Field(default_factory=list)
    failed_decisions: list[str] = Field(default_factory=list)
    outcomes: dict[str, DecisionOutcome] = Field(default_factory=dict)
    halted: bool = False
    halt_reason: Optional[str] = None

    # AtomicToolResult is not a BaseModel-friendly nested shape because
    # it carries arbitrary `Any` blobs; expose it as a dict on the side
    # for callers that need full per-decision detail.
    results: dict[str, Any] = Field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────────
# DAGExecutor
# ─────────────────────────────────────────────────────────────────────


class DAGExecutor:
    """Walks ``execution_order`` from decisions.yaml. Runs every
    decision through the AtomicTool once per application.

    Wave model (matches decisions.yaml exactly):
      - parallel_independent: all five run concurrently (lead_scoring,
        income_verification, credit_assessment, fraud_screening,
        compliance_check). They share no upstream so order doesn't
        matter.
      - sequential_dependent: each entry is a list of decisions that
        run concurrently within the wave; the next wave runs only
        after the previous wave completes.

    Hard-rule enforcement at the executor layer:
      - fraud_block_stops_pipeline: if fraud_screening returns BLOCK,
        every still-unrun decision is short-circuited as
        DECISION_SKIPPED with the fraud-block reason.
      - upstream_block_propagates_to_dependents: handled by the
        AtomicTool / PolicyEvaluator. The executor passes upstream
        summaries through; dependents that should block do so via the
        normal policy path.
      - compliance_block_stops_closing: same — the policy engine
        handles it; the executor only needs to feed the upstream
        summary in."""

    def __init__(
        self,
        *,
        atomic_tool: AtomicTool,
        agents: dict[str, DecisionAgent],
        decisions_config: dict[str, Any],
        event_bus: Optional[EventBus] = None,
    ):
        self._atomic_tool = atomic_tool
        self._agents = dict(agents)
        self._config = decisions_config
        self._event_bus = event_bus or InMemoryEventBus()
        self._decision_index: dict[str, dict[str, Any]] = {
            d["id"]: d for d in self._config.get("decisions", [])
        }
        self._waves: list[list[str]] = self._build_waves()
        self._spec_version: Optional[str] = self._config.get("version")

    # ── Public introspection ─────────────────────────────────────────

    @property
    def event_bus(self) -> EventBus:
        return self._event_bus

    @property
    def waves(self) -> list[list[str]]:
        return [list(w) for w in self._waves]

    # ── Run ──────────────────────────────────────────────────────────

    async def run_application(
        self,
        application_id: str,
        resolver: EntityResolver,
        *,
        evaluation_at: Optional[datetime] = None,
    ) -> ExecutionResult:
        started = datetime.utcnow()
        # `evaluation_at` pins every decision in this DAG run to the
        # same moment for policy-version lookup. Live path leaves it
        # None; replay's full-DAG path passes replay_at so all decisions
        # consult the rule version that was in force at that instant.
        self._evaluation_at = evaluation_at

        upstream_summaries: dict[str, UpstreamSummary] = {}
        outcomes: dict[str, DecisionOutcome] = {}
        results: dict[str, Any] = {}
        completed: list[str] = []
        skipped: list[str] = []
        failed: list[str] = []
        halted = False
        halt_reason: Optional[str] = None
        fraud_blocked = False

        for wave in self._waves:
            wave_runners: list[asyncio.Task[Any]] = []
            wave_decisions: list[str] = []

            for decision_id in wave:
                # ── Skip if not registered ──────────────────────────
                agent = self._agents.get(decision_id)
                if agent is None:
                    skipped.append(decision_id)
                    await self._publish(
                        ExecutionEventType.DECISION_SKIPPED,
                        application_id=application_id,
                        decision_id=decision_id,
                        payload={"reason": "no agent registered"},
                    )
                    continue

                # ── Skip if fraud has already blocked the pipeline ──
                if fraud_blocked and decision_id != "fraud_screening":
                    skipped.append(decision_id)
                    await self._publish(
                        ExecutionEventType.DECISION_SKIPPED,
                        application_id=application_id,
                        decision_id=decision_id,
                        payload={"reason": "fraud_block_stops_pipeline"},
                    )
                    continue

                # ── Skip if any required upstream isn't satisfied ────
                missing = self._missing_upstream(decision_id, outcomes)
                if missing:
                    skipped.append(decision_id)
                    await self._publish(
                        ExecutionEventType.DECISION_SKIPPED,
                        application_id=application_id,
                        decision_id=decision_id,
                        payload={"reason": "upstream_missing", "missing": missing},
                    )
                    continue

                upstream_for_run = self._upstream_for(decision_id, upstream_summaries)
                wave_decisions.append(decision_id)
                wave_runners.append(
                    asyncio.create_task(
                        self._run_one(
                            decision_id=decision_id,
                            agent=agent,
                            application_id=application_id,
                            resolver=resolver,
                            upstream=upstream_for_run,
                        )
                    )
                )

            if not wave_runners:
                continue

            wave_results = await asyncio.gather(
                *wave_runners, return_exceptions=True
            )

            for decision_id, run_result in zip(wave_decisions, wave_results):
                if isinstance(run_result, BaseException):
                    failed.append(decision_id)
                    await self._publish(
                        ExecutionEventType.DECISION_FAILED,
                        application_id=application_id,
                        decision_id=decision_id,
                        payload={"error": repr(run_result)},
                    )
                    continue

                assert isinstance(run_result, AtomicToolResult)
                outcomes[decision_id] = run_result.final_outcome
                results[decision_id] = run_result.model_dump(mode="json")
                upstream_summaries[decision_id] = UpstreamSummary(
                    decision_id=decision_id,
                    outcome=PolicyOutcome(run_result.final_outcome.value),
                    confidence=run_result.reasoning.confidence,
                )
                completed.append(decision_id)

                # Fan out the right event for downstream consumers.
                if run_result.final_outcome == DecisionOutcome.BLOCK:
                    await self._publish(
                        ExecutionEventType.DECISION_BLOCKED,
                        application_id=application_id,
                        decision_id=decision_id,
                        outcome=run_result.final_outcome,
                        payload={"reasons": list(run_result.policy.reasons)},
                    )
                else:
                    await self._publish(
                        ExecutionEventType.DECISION_COMPLETED,
                        application_id=application_id,
                        decision_id=decision_id,
                        outcome=run_result.final_outcome,
                        payload={"action": run_result.routed.action.value},
                    )

                # publish_record_updated → wake_dependents (PRD §13). In a
                # streaming setup this fires the next wave; in this
                # batched walker the wave loop already moves on.
                if run_result.routed.action in (
                    RouteAction.AUTO_WRITEBACK,
                    RouteAction.BLOCK,
                ):
                    await self._publish(
                        ExecutionEventType.RECORD_UPDATED,
                        application_id=application_id,
                        decision_id=decision_id,
                        outcome=run_result.final_outcome,
                        payload={
                            "record_id": run_result.routed.decision_record_id,
                        },
                    )

                # fraud_block_stops_pipeline — if this is the fraud
                # screen and it blocked, every later decision is
                # skipped.
                if (
                    decision_id == "fraud_screening"
                    and run_result.final_outcome == DecisionOutcome.BLOCK
                ):
                    fraud_blocked = True
                    halted = True
                    halt_reason = "fraud_block_stops_pipeline"
                    await self._publish(
                        ExecutionEventType.PIPELINE_HALTED,
                        application_id=application_id,
                        payload={"reason": halt_reason},
                    )

        ended = datetime.utcnow()
        return ExecutionResult(
            application_id=application_id,
            started_at=started,
            ended_at=ended,
            duration_ms=int((ended - started).total_seconds() * 1000),
            completed_decisions=completed,
            skipped_decisions=skipped,
            failed_decisions=failed,
            outcomes=outcomes,
            halted=halted,
            halt_reason=halt_reason,
            results=results,
        )

    # ── Wave construction ────────────────────────────────────────────

    def _build_waves(self) -> list[list[str]]:
        order = self._config.get("execution_order") or {}
        waves: list[list[str]] = []
        parallel = order.get("parallel_independent") or []
        if parallel:
            waves.append(list(parallel))
        for wave in order.get("sequential_dependent") or []:
            if isinstance(wave, list):
                waves.append(list(wave))
            else:
                # tolerate a flat string entry too
                waves.append([wave])

        seen: set[str] = set()
        for wave in waves:
            for decision_id in wave:
                if decision_id in seen:
                    raise DAGExecutorError(
                        f"decision {decision_id!r} appears in execution_order more than once"
                    )
                seen.add(decision_id)
                if decision_id not in self._decision_index:
                    raise DAGExecutorError(
                        f"execution_order references unknown decision {decision_id!r}"
                    )
        return waves

    # ── Dependency helpers ───────────────────────────────────────────

    def _depends_on(self, decision_id: str) -> list[str]:
        spec = self._decision_index.get(decision_id, {})
        return [d["decision"] for d in spec.get("depends_on") or []]

    def _missing_upstream(
        self, decision_id: str, outcomes: dict[str, DecisionOutcome]
    ) -> list[str]:
        return [d for d in self._depends_on(decision_id) if d not in outcomes]

    def _upstream_for(
        self,
        decision_id: str,
        upstream_summaries: dict[str, UpstreamSummary],
    ) -> list[UpstreamSummary]:
        return [
            upstream_summaries[d]
            for d in self._depends_on(decision_id)
            if d in upstream_summaries
        ]

    # ── Single-decision runner ───────────────────────────────────────

    async def _run_one(
        self,
        *,
        decision_id: str,
        agent: DecisionAgent,
        application_id: str,
        resolver: EntityResolver,
        upstream: list[UpstreamSummary],
    ) -> AtomicToolResult:
        await self._publish(
            ExecutionEventType.DECISION_STARTED,
            application_id=application_id,
            decision_id=decision_id,
        )
        return await self._atomic_tool.run(
            agent,
            application_id=application_id,
            resolver=resolver,
            upstream=upstream,
            spec_version=self._spec_version,
            evaluation_at=getattr(self, "_evaluation_at", None),
        )

    # ── Bus convenience ──────────────────────────────────────────────

    async def _publish(
        self,
        type: ExecutionEventType,
        *,
        application_id: str,
        decision_id: Optional[str] = None,
        outcome: Optional[DecisionOutcome] = None,
        payload: Optional[dict[str, Any]] = None,
    ) -> None:
        await self._event_bus.publish(
            ExecutionEvent(
                type=type,
                application_id=application_id,
                decision_id=decision_id,
                outcome=outcome,
                payload=payload or {},
            )
        )

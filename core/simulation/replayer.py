from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from core.context_store import (
    ContextBuilder,
    ContextRecord,
    InMemoryHotCache,
    LendingContextStore,
    Snapshot,
)
from core.decision_agents import (
    AtomicTool,
    AtomicToolResult,
    DecisionAgent,
    RouteAction,
    RoutedDecision,
)
from core.execution.dag_executor import DAGExecutor, InMemoryEventBus
from core.normalizer.models import DecisionMode, DecisionOutcome
from core.policy_engine import (
    DecisionsSpec,
    PolicyEvaluator,
    PolicyOutcome,
    UpstreamSummary,
)
from core.trace import (
    CriticAgent,
    DecisionTrace,
    InMemoryTraceWriter,
    TraceWriter,
)


# ─────────────────────────────────────────────────────────────────────
# STEP 13 — simulation / replay layer.
#
# Re-runs decisions at a frozen point in time. Reads come from the live
# durable store (pinned to the replay timestamp via get_at_time); writes
# go to shadow trace_writer / queue / cache so production state is never
# mutated. The killer use case: "what would persona V2 have decided on
# the funded loans of the last 30 days?" — boot a Replayer over the
# live Platform, swap in the new persona for one decision_id, replay
# every application, compare.
#
# Hard rule: no replay action is allowed to write back into the live
# durable store. Enforced by the _ReadOnlyAtTimeShim (insert_record /
# tombstone raise) and the _ShadowModeRouter (every routed action is
# SHADOW_RECORD, even for BLOCK / AUTO_WRITEBACK outcomes).
# ─────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────
# _ReadOnlyAtTimeShim — wraps a durable store. Reads are pinned; writes
# raise. The shim duck-types the _DurableProtocol shape from
# core/context_store/lending.py so a LendingContextStore composed over
# the shim works unchanged.
# ─────────────────────────────────────────────────────────────────────


class _ReadOnlyAtTimeShim:
    """Read-through wrapper that pins all reads to the replay timestamp.

    `get_latest(...)` proxies to `inner.get_at_time(..., at=replay_at)`
    so callers that don't know about `at` (e.g. ContextBuilder going
    through LendingContextStore.get) still see the frozen world.
    Snapshots are captured on the shim and never reach the live durable
    store — replay traces still get a valid snapshot_id without
    polluting production history."""

    def __init__(self, inner: Any, at: datetime):
        if at is None:
            raise ValueError("_ReadOnlyAtTimeShim requires a pinned `at`")
        self._inner = inner
        self._at = at
        self._snapshots: list[Snapshot] = []

    @property
    def at(self) -> datetime:
        return self._at

    @property
    def inner(self) -> Any:
        return self._inner

    @property
    def captured_snapshots(self) -> list[Snapshot]:
        return list(self._snapshots)

    # ── Reads ────────────────────────────────────────────────────────

    async def get_latest(
        self,
        entity_type: str,
        entity_id: str,
        decision_id: Optional[str],
    ) -> Optional[ContextRecord]:
        return await self._inner.get_at_time(
            entity_type, entity_id, decision_id, self._at
        )

    async def get_at_time(
        self,
        entity_type: str,
        entity_id: str,
        decision_id: Optional[str],
        at: datetime,
    ) -> Optional[ContextRecord]:
        # Cap at the replay frame — never see anything newer than the
        # pinned timestamp, even if a caller asks for a later moment.
        bound = min(at, self._at)
        return await self._inner.get_at_time(
            entity_type, entity_id, decision_id, bound
        )

    async def history(
        self,
        entity_type: str,
        entity_id: str,
        decision_id: Optional[str],
        limit: int,
    ) -> list[ContextRecord]:
        rows = await self._inner.history(
            entity_type, entity_id, decision_id, max(limit * 4, limit + 8)
        )
        out = [
            r for r in rows
            if r.lineage.written_at <= self._at
            and (r.superseded_at is None or r.superseded_at > self._at)
        ]
        return out[:limit]

    # ── Writes — replay must not mutate live store ───────────────────

    async def insert_record(self, record: ContextRecord) -> ContextRecord:
        raise RuntimeError(
            "replay: insert_record forbidden on live durable store"
        )

    async def insert_snapshot(self, snapshot: Snapshot) -> Snapshot:
        # Capture for observability; do NOT propagate to inner.
        self._snapshots.append(snapshot)
        return snapshot

    async def tombstone(self, *args: Any, **kwargs: Any) -> int:
        raise RuntimeError(
            "replay: tombstone forbidden on live durable store"
        )


# ─────────────────────────────────────────────────────────────────────
# _ShadowModeRouter — duck-types ModeRouter. Routes every decision as
# SHADOW_RECORD without touching the durable store. Replays don't need
# to writeback BLOCK / AUTO_WRITEBACK records because the executor
# carries upstream outcomes between waves via its own UpstreamSummary
# state, not via store reads.
# ─────────────────────────────────────────────────────────────────────


class _ShadowModeRouter:
    async def route(
        self,
        *,
        agent_id: str,
        decision_id: str,
        application_id: str,
        mode: DecisionMode,
        outcome: DecisionOutcome,
        confidence: float,
        output_payload: dict[str, Any],
        bundle: Any,
        reasons: Optional[list[str]] = None,
    ) -> RoutedDecision:
        return RoutedDecision(
            action=RouteAction.SHADOW_RECORD,
            final_outcome=outcome,
            mode=mode,
            notes=list(reasons or []) + ["replay: shadow only, no writeback"],
        )


# ─────────────────────────────────────────────────────────────────────
# Result types
# ─────────────────────────────────────────────────────────────────────


class DecisionComparison(BaseModel):
    """Original vs simulated, for one decision_id."""

    decision_id: str
    original_trace_id: Optional[UUID] = None
    original_outcome: Optional[DecisionOutcome] = None
    simulated_outcome: Optional[DecisionOutcome] = None
    outcome_changed: bool = False

    original_confidence: Optional[float] = None
    simulated_confidence: Optional[float] = None
    confidence_delta: Optional[float] = None

    original_matched_clause: Optional[str] = None
    simulated_matched_clause: Optional[str] = None
    matched_clause_changed: bool = False

    original_payload: dict[str, Any] = Field(default_factory=dict)
    simulated_payload: dict[str, Any] = Field(default_factory=dict)
    payload_diff: dict[str, Any] = Field(default_factory=dict)
    payload_changed: bool = False

    persona_swapped: bool = False
    notes: list[str] = Field(default_factory=list)


class ReplayComparison(BaseModel):
    application_id: str
    replay_at: datetime
    total: int
    agreements: int
    disagreements: int
    decision_comparisons: list[DecisionComparison] = Field(default_factory=list)


class ReplayResult(BaseModel):
    application_id: str
    replay_at: datetime
    persona_overrides: list[str] = Field(default_factory=list)
    completed: list[str] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
    failed: list[str] = Field(default_factory=list)
    halted: bool = False
    halt_reason: Optional[str] = None
    outcomes: dict[str, DecisionOutcome] = Field(default_factory=dict)
    comparison: ReplayComparison


# ─────────────────────────────────────────────────────────────────────
# Replayer
# ─────────────────────────────────────────────────────────────────────


class Replayer:
    """Replays decisions at a frozen point in time.

    Construct with the live components (use Replayer.from_platform for
    the common case). Two entry points:

      replay_application(application_id, *, at=None, persona_overrides=None)
        → re-run the full DAG against shadow stores. Useful for
          backtesting "would persona V2 have closed this loan?"

      replay_decision(application_id, decision_id, *, at=None,
                      persona_override=None)
        → re-run a single decision. Upstream summaries are reconstructed
          from the live trace_writer at `at`, not from the simulation.

    `at` defaults to the latest known trace timestamp for the
    application, so the natural meaning of `replay_application(app_id)`
    is "re-run as if it were the moment the live pipeline finished" —
    reproducible across calls.
    """

    def __init__(
        self,
        *,
        store: LendingContextStore,
        evaluator: PolicyEvaluator,
        spec: DecisionsSpec,
        trace_writer: TraceWriter,
        agents: dict[str, DecisionAgent],
        critic: Optional[CriticAgent] = None,
        policy_store: Optional[Any] = None,
        retriever_factory: Optional[Any] = None,
    ):
        self._store = store
        self._evaluator = evaluator
        self._spec = spec
        self._trace_writer = trace_writer
        self._agents = dict(agents)
        self._critic = critic
        # Optional — when set, replay's AtomicTool consults the same
        # policy store the live pipeline did, so policy_version_id stamps
        # appear on simulated traces too. Live durable is wrapped in the
        # read-only shim, but the policy store itself is read-only by
        # contract during replay (we never write to it from a shadow
        # AtomicTool).
        self._policy_store = policy_store
        # Callable: (shadow_store) -> Retriever. Called per replay so
        # the retriever's KnowledgeStore wraps the shadow store (which
        # in turn wraps the at-time shim) — claim reads pin to
        # replay_at automatically.
        self._retriever_factory = retriever_factory

    @classmethod
    def from_platform(cls, platform: Any) -> "Replayer":
        """Construct from an api.deps.Platform without importing it.

        Duck-typed: any object exposing the required attributes works.
        Keeps core/simulation independent of api/."""

        # Build a factory that constructs a fresh Retriever wrapping
        # whatever shadow store the replayer hands it. This way the
        # retriever's reads pin to replay_at via the shim, with no
        # mutation of the live KnowledgeStore.
        def _retriever_factory(shadow_store: LendingContextStore):
            from core.knowledge import KnowledgeStore, MetadataRetriever
            ks = KnowledgeStore(shadow_store)
            return MetadataRetriever(ks)

        return cls(
            store=platform.store,
            evaluator=platform.evaluator,
            spec=platform.spec,
            trace_writer=platform.trace_writer,
            agents=platform.agents,
            critic=getattr(platform, "critic", None),
            policy_store=getattr(platform, "policy_store", None),
            retriever_factory=_retriever_factory if getattr(platform, "retriever", None) else None,
        )

    # ── Public entry points ──────────────────────────────────────────

    async def replay_application(
        self,
        application_id: str,
        *,
        at: Optional[datetime] = None,
        persona_overrides: Optional[dict[str, DecisionAgent]] = None,
        include_critic: bool = False,
    ) -> ReplayResult:
        replay_at = at or await self._latest_trace_time(application_id) or datetime.utcnow()
        overrides = persona_overrides or {}
        for did, agent in overrides.items():
            if agent.decision_id != did:
                raise ValueError(
                    f"persona_overrides[{did!r}].decision_id={agent.decision_id!r} "
                    "does not match the override key"
                )

        shadow = self._build_shadow(replay_at, include_critic=include_critic)

        agents = dict(self._agents)
        agents.update(overrides)

        executor = DAGExecutor(
            atomic_tool=shadow.atomic_tool,
            agents=agents,
            decisions_config=self._spec.to_dict(),
            event_bus=InMemoryEventBus(),
        )
        exec_result = await executor.run_application(
            application_id, shadow.resolver, evaluation_at=replay_at
        )

        sim_traces = await shadow.trace_writer.list_for_application(application_id)
        comparison = await self._compare_application(
            application_id=application_id,
            replay_at=replay_at,
            simulated_traces=sim_traces,
            persona_overrides=set(overrides.keys()),
        )

        return ReplayResult(
            application_id=application_id,
            replay_at=replay_at,
            persona_overrides=sorted(overrides.keys()),
            completed=exec_result.completed_decisions,
            skipped=exec_result.skipped_decisions,
            failed=exec_result.failed_decisions,
            halted=exec_result.halted,
            halt_reason=exec_result.halt_reason,
            outcomes=exec_result.outcomes,
            comparison=comparison,
        )

    async def replay_decision(
        self,
        application_id: str,
        decision_id: str,
        *,
        at: Optional[datetime] = None,
        persona_override: Optional[DecisionAgent] = None,
        include_critic: bool = False,
    ) -> tuple[AtomicToolResult, DecisionComparison]:
        if persona_override is not None and persona_override.decision_id != decision_id:
            raise ValueError(
                f"persona_override.decision_id={persona_override.decision_id!r} "
                f"does not match {decision_id!r}"
            )
        replay_at = at or await self._latest_trace_time(application_id) or datetime.utcnow()

        agent = persona_override or self._agents.get(decision_id)
        if agent is None:
            raise ValueError(
                f"no agent registered for decision_id={decision_id!r} "
                "and no persona_override supplied"
            )

        shadow = self._build_shadow(replay_at, include_critic=include_critic)

        upstream = await self._build_upstream_from_traces(
            application_id, decision_id, replay_at
        )
        result = await shadow.atomic_tool.run(
            agent,
            application_id=application_id,
            resolver=shadow.resolver,
            upstream=upstream,
            spec_version=self._spec.version,
            evaluation_at=replay_at,
        )

        original = await self._latest_original_trace(
            application_id, decision_id, replay_at
        )
        comparison = _compare_one(
            decision_id,
            original=original,
            simulated_trace=result.trace,
            persona_swapped=persona_override is not None,
        )
        return result, comparison

    # ── Shadow assembly ──────────────────────────────────────────────

    def _build_shadow(
        self, replay_at: datetime, *, include_critic: bool
    ) -> "_ShadowComponents":
        shim = _ReadOnlyAtTimeShim(self._raw_durable(), replay_at)
        store = LendingContextStore(InMemoryHotCache(), shim)
        retriever = (
            self._retriever_factory(store)
            if self._retriever_factory is not None
            else None
        )
        builder = ContextBuilder(store, self._spec.to_dict(), retriever=retriever)
        router = _ShadowModeRouter()
        trace_writer = InMemoryTraceWriter()
        critic = self._critic if include_critic else None
        atomic_tool = AtomicTool(
            builder=builder,
            evaluator=self._evaluator,
            critic=critic,
            trace_writer=trace_writer,
            router=router,  # type: ignore[arg-type]
            policy_store=self._policy_store,
        )
        resolver = _build_replay_resolver(shim, replay_at)
        return _ShadowComponents(
            shim=shim,
            store=store,
            builder=builder,
            atomic_tool=atomic_tool,
            trace_writer=trace_writer,
            resolver=resolver,
        )

    def _raw_durable(self) -> Any:
        # LendingContextStore composes a durable backend; reach through.
        # Both InMemoryDurableStore and PostgresDurableStore expose the
        # same _DurableProtocol shape so the shim works against either.
        return self._store._durable  # type: ignore[attr-defined]

    # ── Trace lookups ────────────────────────────────────────────────

    async def _latest_trace_time(self, application_id: str) -> Optional[datetime]:
        traces = await self._trace_writer.list_for_application(application_id)
        if not traces:
            return None
        return max((t.ended_at or t.started_at) for t in traces)

    async def _latest_original_trace(
        self,
        application_id: str,
        decision_id: str,
        at: datetime,
    ) -> Optional[DecisionTrace]:
        traces = await self._trace_writer.list_for_application(application_id)
        candidates = [
            t for t in traces
            if t.decision_id == decision_id and t.started_at <= at
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda t: t.started_at)

    async def _build_upstream_from_traces(
        self,
        application_id: str,
        decision_id: str,
        at: datetime,
    ) -> list[UpstreamSummary]:
        spec = self._spec.decision(decision_id)
        upstream_ids = [d["decision"] for d in spec.get("depends_on") or []]
        if not upstream_ids:
            return []
        traces = await self._trace_writer.list_for_application(application_id)
        latest: dict[str, DecisionTrace] = {}
        for t in traces:
            if t.decision_id not in upstream_ids or t.started_at > at:
                continue
            cur = latest.get(t.decision_id)
            if cur is None or t.started_at > cur.started_at:
                latest[t.decision_id] = t
        return [
            UpstreamSummary(
                decision_id=did,
                outcome=PolicyOutcome(latest[did].outcome.value),
                confidence=latest[did].confidence,
            )
            for did in upstream_ids
            if did in latest
        ]

    # ── Comparison ───────────────────────────────────────────────────

    async def _compare_application(
        self,
        *,
        application_id: str,
        replay_at: datetime,
        simulated_traces: list[DecisionTrace],
        persona_overrides: set[str],
    ) -> ReplayComparison:
        sim_by_decision: dict[str, DecisionTrace] = {}
        for t in simulated_traces:
            cur = sim_by_decision.get(t.decision_id)
            if cur is None or t.started_at > cur.started_at:
                sim_by_decision[t.decision_id] = t

        original_traces = await self._trace_writer.list_for_application(application_id)
        orig_by_decision: dict[str, DecisionTrace] = {}
        for t in original_traces:
            if t.started_at > replay_at:
                continue
            cur = orig_by_decision.get(t.decision_id)
            if cur is None or t.started_at > cur.started_at:
                orig_by_decision[t.decision_id] = t

        all_decisions = sorted(set(sim_by_decision) | set(orig_by_decision))
        comparisons: list[DecisionComparison] = []
        agreements = 0
        disagreements = 0
        for did in all_decisions:
            cmp_obj = _compare_one(
                did,
                original=orig_by_decision.get(did),
                simulated_trace=sim_by_decision.get(did),
                persona_swapped=did in persona_overrides,
            )
            if cmp_obj.original_outcome is not None and cmp_obj.simulated_outcome is not None:
                if cmp_obj.outcome_changed:
                    disagreements += 1
                else:
                    agreements += 1
            comparisons.append(cmp_obj)

        return ReplayComparison(
            application_id=application_id,
            replay_at=replay_at,
            total=len(comparisons),
            agreements=agreements,
            disagreements=disagreements,
            decision_comparisons=comparisons,
        )


# ─────────────────────────────────────────────────────────────────────
# Internal scaffolding
# ─────────────────────────────────────────────────────────────────────


class _ShadowComponents:
    __slots__ = ("shim", "store", "builder", "atomic_tool", "trace_writer", "resolver")

    def __init__(
        self,
        *,
        shim: _ReadOnlyAtTimeShim,
        store: LendingContextStore,
        builder: ContextBuilder,
        atomic_tool: AtomicTool,
        trace_writer: InMemoryTraceWriter,
        resolver: Any,
    ):
        self.shim = shim
        self.store = store
        self.builder = builder
        self.atomic_tool = atomic_tool
        self.trace_writer = trace_writer
        self.resolver = resolver


def _build_replay_resolver(shim: _ReadOnlyAtTimeShim, at: datetime):
    """Resolver mirroring api.deps._default_resolver but pinned in time.

    Walks the inner durable's record list, filters records to those that
    existed at `at` (written before, not yet superseded). The Postgres
    swap will need a SQL implementation — same shape as the live
    resolver, with the same Postgres-path TODO."""

    inner_records = getattr(shim.inner, "_records", None)

    async def _resolve(object_type_id: str, application_id: str) -> list[str]:
        if not isinstance(inner_records, list):
            return []
        latest_by_id: dict[str, ContextRecord] = {}
        for rec in inner_records:
            if rec.entity_type != object_type_id:
                continue
            if rec.decision_id is not None:
                continue
            if rec.lineage.written_at > at:
                continue
            if rec.superseded_at is not None and rec.superseded_at <= at:
                continue
            current = latest_by_id.get(rec.entity_id)
            if current is None or rec.version > current.version:
                latest_by_id[rec.entity_id] = rec

        ids: list[str] = []
        for entity_id, rec in latest_by_id.items():
            value = rec.value if isinstance(rec.value, dict) else {}
            if object_type_id == "Application":
                if entity_id == application_id:
                    ids.append(entity_id)
                continue
            if object_type_id == "Applicant":
                ids.append(entity_id)
                continue
            if value.get("application_id") in (application_id, None):
                ids.append(entity_id)
        return ids

    return _resolve


def _compare_one(
    decision_id: str,
    *,
    original: Optional[DecisionTrace],
    simulated_trace: Optional[DecisionTrace],
    persona_swapped: bool,
) -> DecisionComparison:
    cmp_obj = DecisionComparison(
        decision_id=decision_id,
        persona_swapped=persona_swapped,
    )
    if original is not None:
        cmp_obj.original_trace_id = original.trace_id
        cmp_obj.original_outcome = original.outcome
        cmp_obj.original_confidence = original.confidence
        cmp_obj.original_matched_clause = original.matched_clause
        cmp_obj.original_payload = dict(original.output_payload or {})
    if simulated_trace is not None:
        cmp_obj.simulated_outcome = simulated_trace.outcome
        cmp_obj.simulated_confidence = simulated_trace.confidence
        cmp_obj.simulated_matched_clause = simulated_trace.matched_clause
        cmp_obj.simulated_payload = dict(simulated_trace.output_payload or {})

    if cmp_obj.original_outcome is not None and cmp_obj.simulated_outcome is not None:
        cmp_obj.outcome_changed = cmp_obj.original_outcome != cmp_obj.simulated_outcome
    if cmp_obj.original_confidence is not None and cmp_obj.simulated_confidence is not None:
        cmp_obj.confidence_delta = round(
            cmp_obj.simulated_confidence - cmp_obj.original_confidence, 6
        )
    if cmp_obj.original_matched_clause != cmp_obj.simulated_matched_clause:
        cmp_obj.matched_clause_changed = (
            cmp_obj.original_matched_clause is not None
            or cmp_obj.simulated_matched_clause is not None
        )
    cmp_obj.payload_diff = _payload_diff(cmp_obj.original_payload, cmp_obj.simulated_payload)
    cmp_obj.payload_changed = bool(
        cmp_obj.payload_diff.get("added")
        or cmp_obj.payload_diff.get("removed")
        or cmp_obj.payload_diff.get("changed")
    )

    if original is None:
        cmp_obj.notes.append("no original trace at or before replay_at")
    if simulated_trace is None:
        cmp_obj.notes.append("simulation produced no trace for this decision")
    if persona_swapped:
        cmp_obj.notes.append("persona override applied")
    return cmp_obj


def _payload_diff(
    original: dict[str, Any], simulated: dict[str, Any]
) -> dict[str, Any]:
    added = {k: simulated[k] for k in simulated if k not in original}
    removed = {k: original[k] for k in original if k not in simulated}
    changed = {
        k: {"original": original[k], "simulated": simulated[k]}
        for k in original
        if k in simulated and original[k] != simulated[k]
    }
    return {"added": added, "removed": removed, "changed": changed}


__all__ = [
    "DecisionComparison",
    "ReplayComparison",
    "ReplayResult",
    "Replayer",
]

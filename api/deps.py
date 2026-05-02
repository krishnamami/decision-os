from __future__ import annotations

from pathlib import Path
from typing import Any, Awaitable, Callable, Optional, Union

from core.connectors import BaseConnector, EventSink
from core.context_store import (
    ContextBuilder,
    InMemoryDurableStore,
    InMemoryHotCache,
    LendingContextStore,
)
from core.decision_agents import (
    AtomicTool,
    DecisionAgent,
    InMemoryHumanQueue,
    ModeRouter,
)
from core.execution.dag_executor import DAGExecutor, InMemoryEventBus
from core.policy_engine import DecisionsSpec, PolicyEvaluator, load_spec
from core.trace import (
    CriticAgent,
    InMemoryLearningStore,
    InMemoryTraceWriter,
    LearningStore,
    ReflectionService,
    TraceWriter,
)

from .ingest import EntityHydrator, EventLog, build_event_sink


# ─────────────────────────────────────────────────────────────────────
# Platform — single container for the live runtime.
#
# Routes get this via FastAPI's Depends. Tests construct a Platform
# directly with whatever swap-ins they need (mock TraceWriter,
# pre-loaded LearningStore, alternative ContextBuilder). Keeping the
# container shallow — no factories, no service-locator magic — so the
# wiring is obvious at every call site.
# ─────────────────────────────────────────────────────────────────────


# Caller-supplied async resolver: (object_type_id, application_id) → list[entity_id]
EntityResolverFn = Callable[[str, str], Awaitable[list[str]]]


class Platform:
    """Runtime container assembled at startup.

    Holds the live LendingContextStore + ContextBuilder + PolicyEvaluator
    + AtomicTool + DAGExecutor + ReflectionService + EventLog +
    EntityHydrator. Also owns two registries:
      - agents:     decision_id → DecisionAgent. Populated by domain
                    pack startup (domains/lending/personas/__init__.py
                    will register here).
      - connectors: source_system → BaseConnector. Populated by webhook
                    setup; POST /connectors/webhook/{source} looks up
                    by source_system."""

    def __init__(
        self,
        *,
        spec: DecisionsSpec,
        store: LendingContextStore,
        builder: ContextBuilder,
        evaluator: PolicyEvaluator,
        critic: Optional[CriticAgent],
        trace_writer: TraceWriter,
        learning_store: LearningStore,
        reflection: ReflectionService,
        event_log: EventLog,
        hydrator: EntityHydrator,
        sink: EventSink,
        atomic_tool: AtomicTool,
        mode_router: ModeRouter,
        human_queue: InMemoryHumanQueue,
        entity_resolver: EntityResolverFn,
    ):
        self.spec = spec
        self.store = store
        self.builder = builder
        self.evaluator = evaluator
        self.critic = critic
        self.trace_writer = trace_writer
        self.learning_store = learning_store
        self.reflection = reflection
        self.event_log = event_log
        self.hydrator = hydrator
        self.sink = sink
        self.atomic_tool = atomic_tool
        self.mode_router = mode_router
        self.human_queue = human_queue
        self.entity_resolver = entity_resolver

        self.agents: dict[str, DecisionAgent] = {}
        self.connectors: dict[str, BaseConnector] = {}
        self._executor: Optional[DAGExecutor] = None
        self._executor_dirty = True

    # ── Registries ───────────────────────────────────────────────────

    def register_agent(self, agent: DecisionAgent) -> None:
        if agent.decision_id not in self.spec.decision_index:
            raise ValueError(
                f"agent.decision_id {agent.decision_id!r} not in decisions.yaml"
            )
        self.agents[agent.decision_id] = agent
        self._executor_dirty = True

    def register_connector(self, connector: BaseConnector) -> None:
        self.connectors[connector.source_system] = connector

    # ── DAG executor (lazy; rebuilds when agents change) ─────────────

    def executor(self) -> DAGExecutor:
        if self._executor is None or self._executor_dirty:
            self._executor = DAGExecutor(
                atomic_tool=self.atomic_tool,
                agents=self.agents,
                decisions_config=self.spec.to_dict(),
                event_bus=InMemoryEventBus(),
            )
            self._executor_dirty = False
        return self._executor


# ─────────────────────────────────────────────────────────────────────
# Default builder — assembles everything from the YAML spec in-memory.
#
# Production swaps PostgresDurableStore + RedisHotCache for the in-memory
# variants, but the wiring is identical otherwise. Real-backend
# verification (the routine landing on May 3) does exactly that swap and
# replays the same DAG smoke against live Postgres + Redis.
# ─────────────────────────────────────────────────────────────────────


def _default_resolver(store: LendingContextStore) -> EntityResolverFn:
    """Resolver used when a caller doesn't pass one in.

    Walks the SHARED scope of the durable store and returns every active
    entity_id whose object_type matches and whose record either is the
    Application itself or carries a matching application_id. Cheap,
    dependency-free, correct for the in-memory backend; the production
    swap is a SQL ``SELECT entity_id ... WHERE entity_type = $1 AND
    decision_id IS NULL`` plus the same filter."""

    durable = store._durable  # type: ignore[attr-defined]

    async def _resolve(object_type_id: str, application_id: str) -> list[str]:
        records = getattr(durable, "_records", None)
        if not isinstance(records, list):
            return []
        latest_by_id: dict[str, Any] = {}
        for rec in records:
            if rec.entity_type != object_type_id:
                continue
            if rec.decision_id is not None:
                continue
            if rec.superseded_at is not None:
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
            # Applicant has no application_id field; keep all applicants
            # the test fixture wrote — there's typically one per app in
            # the seed scenarios.
            if object_type_id == "Applicant":
                ids.append(entity_id)
                continue
            if value.get("application_id") in (application_id, None):
                ids.append(entity_id)
        return ids

    return _resolve


def build_default_platform(
    decisions_path: Union[str, Path] = "domains/lending/decisions.yaml",
    *,
    entity_resolver: Optional[EntityResolverFn] = None,
    critic: Optional[CriticAgent] = None,
) -> Platform:
    """Assemble a Platform with all in-memory backends ready to serve."""

    spec = load_spec(decisions_path)

    hot = InMemoryHotCache()
    durable = InMemoryDurableStore()
    store = LendingContextStore(hot, durable)

    builder = ContextBuilder(store, spec.to_dict())
    evaluator = PolicyEvaluator(spec.to_dict())
    trace_writer = InMemoryTraceWriter()
    learning_store = InMemoryLearningStore()
    reflection = ReflectionService(
        learning_store,
        retention_days=int(spec.reflection.get("retention_days", 365) or 365),
    )

    queue = InMemoryHumanQueue()
    mode_router = ModeRouter(store, queue)
    atomic_tool = AtomicTool(
        builder=builder,
        evaluator=evaluator,
        critic=critic or CriticAgent(),
        trace_writer=trace_writer,
        router=mode_router,
    )

    event_log = EventLog()
    hydrator = EntityHydrator(store)
    sink = build_event_sink(event_log, hydrator)

    resolver = entity_resolver or _default_resolver(store)

    return Platform(
        spec=spec,
        store=store,
        builder=builder,
        evaluator=evaluator,
        critic=critic,
        trace_writer=trace_writer,
        learning_store=learning_store,
        reflection=reflection,
        event_log=event_log,
        hydrator=hydrator,
        sink=sink,
        atomic_tool=atomic_tool,
        mode_router=mode_router,
        human_queue=queue,
        entity_resolver=resolver,
    )


__all__ = [
    "EntityResolverFn",
    "Platform",
    "build_default_platform",
]

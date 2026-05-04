from __future__ import annotations

from pathlib import Path
from typing import Any, Awaitable, Callable, Optional, Union

from core.audit import (
    AlertSink,
    AuditEngine,
    AuditStore,
    InMemoryAlertSink,
    InMemoryAuditStore,
)
from core.audit.pii_log import InMemoryPIIAccessLog, PIIAccessLog
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
from core.knowledge import KnowledgeStore, MetadataRetriever, Retriever
from core.policy_engine import (
    DecisionsSpec,
    PolicyEvaluator,
    PolicyStore,
    load_spec,
)
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
        policy_store: PolicyStore,
        knowledge_store: KnowledgeStore,
        retriever: Retriever,
        audit_engine: AuditEngine,
        audit_store: AuditStore,
        audit_alert_sink: AlertSink,
        pii_access_log: PIIAccessLog,
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
        self.policy_store = policy_store
        self.knowledge_store = knowledge_store
        self.retriever = retriever
        self.audit_engine = audit_engine
        self.audit_store = audit_store
        self.audit_alert_sink = audit_alert_sink
        self.pii_access_log = pii_access_log

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

    Walks the SHARED scope of the durable store and returns the
    entity_ids that belong to ``application_id``. Two scoping rules:

      Application-bound entities (Application, Property, Loan,
        ComplianceRecord) — filter by ``value.application_id ==
        application_id``.
      Applicant-bound entities (Applicant, FraudProfile, CreditProfile,
        IncomeProfile) — look up the Application's applicant_id, then
        filter by ``value.applicant_id == applicant_id``.

    Cheap, dependency-free, correct for the in-memory backend. The
    production swap is two SQL SELECTs (one for the Application-row
    join + one for the matching profiles).

    Earlier versions had a bug here — Applicant-bound entities all have
    ``application_id=None`` because they belong to the applicant, not
    the application. The previous resolver matched on
    ``value.application_id in (application_id, None)`` which let ALL
    FraudProfile records (any applicant) into every application's
    bundle. When scenarios shared a platform this produced
    non-deterministic outcomes (latest_object picked one cross-tenant
    profile over another based on sub-second timestamp ties).
    Session 9 fix: filter by applicant_id explicitly."""

    durable = store._durable  # type: ignore[attr-defined]

    APPLICANT_BOUND = {"Applicant", "FraudProfile", "CreditProfile", "IncomeProfile"}

    async def _resolve(object_type_id: str, application_id: str) -> list[str]:
        records = getattr(durable, "_records", None)
        if not isinstance(records, list):
            return []

        # Find this Application's applicant_id. Applicant-bound entity
        # filtering depends on it; if the Application doesn't carry one
        # (legacy / partial-hydration cases) those entities can't be
        # filtered safely, so return [] rather than leaking other
        # applicants' data.
        applicant_id: Optional[str] = None
        for rec in records:
            if (
                rec.entity_type == "Application"
                and rec.entity_id == application_id
                and rec.decision_id is None
                and rec.superseded_at is None
            ):
                value = rec.value if isinstance(rec.value, dict) else {}
                applicant_id = value.get("applicant_id") or None
                break

        # Latest active record per entity_id for the requested type.
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

            if object_type_id in APPLICANT_BOUND:
                if applicant_id is None:
                    continue  # safer to drop than to leak
                if value.get("applicant_id") == applicant_id:
                    ids.append(entity_id)
                continue

            # Application-bound default — Property / Loan / ComplianceRecord.
            if value.get("application_id") == application_id:
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
    pii_access_log: PIIAccessLog = InMemoryPIIAccessLog()
    store = LendingContextStore(hot, durable, pii_access_log=pii_access_log)

    knowledge_store = KnowledgeStore(store)
    retriever = MetadataRetriever(knowledge_store)

    builder = ContextBuilder(store, spec.to_dict(), retriever=retriever)
    evaluator = PolicyEvaluator(spec.to_dict())
    trace_writer = InMemoryTraceWriter()
    learning_store = InMemoryLearningStore()
    reflection = ReflectionService(
        learning_store,
        retention_days=int(spec.reflection.get("retention_days", 365) or 365),
    )

    queue = InMemoryHumanQueue()
    mode_router = ModeRouter(store, queue)

    policy_store = PolicyStore(store)

    audit_alert_sink: AlertSink = InMemoryAlertSink()
    audit_engine = AuditEngine(alert_sink=audit_alert_sink)
    audit_store: AuditStore = InMemoryAuditStore()

    atomic_tool = AtomicTool(
        builder=builder,
        evaluator=evaluator,
        critic=critic or CriticAgent(),
        trace_writer=trace_writer,
        router=mode_router,
        policy_store=policy_store,
        audit_engine=audit_engine,
        audit_store=audit_store,
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
        policy_store=policy_store,
        knowledge_store=knowledge_store,
        retriever=retriever,
        audit_engine=audit_engine,
        audit_store=audit_store,
        audit_alert_sink=audit_alert_sink,
        pii_access_log=pii_access_log,
    )


__all__ = [
    "EntityResolverFn",
    "Platform",
    "build_default_platform",
]

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional, Protocol, Union
from uuid import UUID

from pydantic import BaseModel, Field

from core.ontology import LENDING_OBJECT_TYPES, ObjectType

from .lending import LendingContextStore


# ─────────────────────────────────────────────────────────────────────
# ContextBundle — what the decision agent actually receives.
#
# The bundle is the LLM's view of the world for one decision. It is
# typed, immutable, decision-scoped, and lineage-stamped (via the
# upstream snapshot id). Anything the agent reasons over must come from
# this bundle — that's the contract that lets us replay decisions
# deterministically from trace.
# ─────────────────────────────────────────────────────────────────────


class ContextBundle(BaseModel):
    """Frozen, decision-scoped context handed to a decision agent."""

    decision_id: str
    application_id: str
    snapshot_id: UUID
    snapshot_at: datetime
    context_window_days: Optional[int] = None

    # ot_id → entity_id → field projection (filtered by ObjectType.to_context_bundle)
    objects: dict[str, dict[str, dict[str, Any]]] = Field(default_factory=dict)

    # upstream decision_id → output value blob from prior decision write
    upstream_outputs: dict[str, dict[str, Any]] = Field(default_factory=dict)
    upstream_decision_ids: list[str] = Field(default_factory=list)

    # Knowledge Context Layer — claims extracted from EDMS-sourced
    # documents, filtered through the doc_type → decisions matrix in
    # knowledge_base.json. claims is the simple {field_name → value}
    # shape decision agents read directly. claim_records carries the
    # full provenance (status, page, verifier, extraction_confidence)
    # for the trace. See core/knowledge/retriever.py.
    claims: dict[str, Any] = Field(default_factory=dict)
    claim_records: list[Any] = Field(default_factory=list)
    documents: list[Any] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────
# Resolver — turns (object_type_id, application_id) into entity ids.
#
# Different object types have different scoping rules — Applicant is
# referenced via Application.applicant_id, CreditProfile/IncomeProfile/
# FraudProfile belong to the Applicant (not the Application), Property
# and ComplianceRecord belong to the Application. The builder doesn't
# know any of that — the caller's resolver does.
# ─────────────────────────────────────────────────────────────────────


EntityKey = tuple[str, str]                     # (object_type_id, entity_id)
ResolverResult = Union[list[str], Awaitable[list[str]]]


class EntityResolver(Protocol):
    def __call__(self, object_type_id: str, application_id: str) -> ResolverResult: ...


async def _maybe_await(value: ResolverResult) -> list[str]:
    if hasattr(value, "__await__"):
        return await value  # type: ignore[no-any-return]
    return value  # type: ignore[return-value]


# ─────────────────────────────────────────────────────────────────────
# Decision spec loading — a thin wrapper over decisions.yaml.
#
# Accepts either a path or a pre-parsed dict so tests don't need PyYAML
# installed. PyYAML is imported lazily.
# ─────────────────────────────────────────────────────────────────────


DecisionsConfig = dict[str, Any]


def load_decisions_config(path: Union[str, Path]) -> DecisionsConfig:
    try:
        import yaml  # type: ignore
    except ImportError as err:  # pragma: no cover
        raise ImportError(
            "PyYAML is required to load decisions.yaml; "
            "install with `pip install pyyaml` or pass a parsed dict directly"
        ) from err
    with Path(path).open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


# ─────────────────────────────────────────────────────────────────────
# ContextBuilder
# ─────────────────────────────────────────────────────────────────────


class ContextBuilder:
    """Assembles a decision-scoped ContextBundle from the durable store.

    Pipeline:
      1. Look up the decision spec in decisions.yaml.
      2. Resolve which object types this decision is allowed to read
         (ontology.decisions_that_read_it — least privilege at data layer).
      3. Use the caller's resolver to expand each readable object type
         into concrete entity_ids for this application.
      4. Snapshot via the durable store, including upstream decision
         outputs from depends_on.
      5. Project each entity dict through ObjectType.to_context_bundle
         to drop fields the decision is not authorized to read.

    Hard rules backed:
      no_agent_without_permissions  — projection is enforced; an entity
                                      whose object type is not listed in
                                      decisions_that_read_it is dropped.
      no_context_without_lineage    — store.snapshot() pins the exact
                                      record_ids the bundle was built from.
    """

    # ObjectTypes served by the Knowledge Context Layer (Retriever),
    # not by the per-loan entity resolver. Excluded from
    # readable_object_types so build() doesn't snapshot them as
    # `objects` — they flow into bundle.claims / bundle.claim_records /
    # bundle.documents instead.
    KNOWLEDGE_OBJECT_TYPES: tuple[str, ...] = ("Document", "Claim")

    # ObjectTypes used by the policy_engine — Type-2 versioned across
    # all applications. Not per-loan entities; excluded from the resolver
    # path so they don't flood every bundle's objects map.
    POLICY_OBJECT_TYPES: tuple[str, ...] = ("Policy", "PolicyVersion")

    def __init__(
        self,
        store: LendingContextStore,
        decisions_config: DecisionsConfig,
        object_types: Optional[dict[str, ObjectType]] = None,
        retriever: Optional[Any] = None,
    ):
        self._store = store
        self._config = decisions_config
        self._object_types = object_types or LENDING_OBJECT_TYPES
        # Optional. When set, build() pulls verified claims for this
        # decision via the Retriever Protocol. None falls back to
        # empty bundle.claims (legacy / tests that don't need docs).
        self._retriever = retriever

        decisions = self._config.get("decisions", [])
        self._decision_index: dict[str, dict[str, Any]] = {d["id"]: d for d in decisions}

    @classmethod
    def from_files(
        cls,
        store: LendingContextStore,
        decisions_path: Union[str, Path],
        object_types: Optional[dict[str, ObjectType]] = None,
    ) -> "ContextBuilder":
        return cls(store, load_decisions_config(decisions_path), object_types)

    # ── Spec inspection ──────────────────────────────────────────────

    def decision_spec(self, decision_id: str) -> dict[str, Any]:
        try:
            return self._decision_index[decision_id]
        except KeyError as err:
            raise KeyError(f"unknown decision_id: {decision_id!r}") from err

    def upstream_decision_ids(self, decision_id: str) -> list[str]:
        spec = self.decision_spec(decision_id)
        return [d["decision"] for d in spec.get("depends_on") or []]

    def readable_object_types(self, decision_id: str) -> list[ObjectType]:
        excluded = set(self.KNOWLEDGE_OBJECT_TYPES) | set(self.POLICY_OBJECT_TYPES)
        return [
            ot for ot in self._object_types.values()
            if decision_id in ot.decisions_that_read_it
            and ot.object_type_id not in excluded
        ]

    # ── Build ────────────────────────────────────────────────────────

    async def build(
        self,
        application_id: str,
        decision_id: str,
        resolver: EntityResolver,
    ) -> ContextBundle:
        spec = self.decision_spec(decision_id)
        upstream = self.upstream_decision_ids(decision_id)
        readable = self.readable_object_types(decision_id)

        entity_keys: list[EntityKey] = []
        for ot in readable:
            entity_ids = await _maybe_await(resolver(ot.object_type_id, application_id))
            for eid in entity_ids:
                entity_keys.append((ot.object_type_id, eid))

        snapshot = await self._store.snapshot(
            application_id=application_id,
            decision_id=decision_id,
            entity_keys=entity_keys,
            upstream_decision_ids=upstream,
        )

        # Project each entity dict through ObjectType.to_context_bundle.
        # Anything not listed in decisions_that_read_it is silently
        # dropped — the snapshot may contain extras (e.g. shared records
        # written outside of this decision's scope) but the bundle the
        # agent sees is filtered to its read perms.
        projected: dict[str, dict[str, dict[str, Any]]] = {}
        for ot_id, entities in snapshot.context.items():
            if ot_id == "decision":
                continue
            ot = self._object_types.get(ot_id)
            if ot is None or decision_id not in ot.decisions_that_read_it:
                continue
            projected[ot_id] = {}
            for entity_id, value in entities.items():
                projected[ot_id][entity_id] = ot.to_context_bundle(value, decision_id)

        upstream_outputs: dict[str, dict[str, Any]] = {
            up_id: payload for up_id, payload in snapshot.context.get("decision", {}).items()
        }

        # Knowledge Context — fetched via Retriever, NOT through the
        # resolver path. Verified claims by default; the retriever
        # honours the doc_type → decisions matrix. None retriever leaves
        # the claim fields empty (legacy / tests).
        claims: dict[str, Any] = {}
        claim_records: list[Any] = []
        documents: list[Any] = []
        if self._retriever is not None:
            retrieval = await self._retriever.retrieve(
                decision_id, application_id
            )
            claims = dict(retrieval.claims_by_field)
            claim_records = list(retrieval.claim_records)
            documents = list(retrieval.documents)

        return ContextBundle(
            decision_id=decision_id,
            application_id=application_id,
            snapshot_id=snapshot.id,
            snapshot_at=snapshot.snapshot_at,
            context_window_days=spec.get("context_window_days"),
            objects=projected,
            upstream_outputs=upstream_outputs,
            upstream_decision_ids=list(upstream),
            claims=claims,
            claim_records=claim_records,
            documents=documents,
        )

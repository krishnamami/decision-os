"""AtomicTool tests — bundled call from PRD §7.

Covers the integration choke point: context_build → policy_check →
agent.reason → policy_check → critic → trace_write → mode_route, all in
one bundled call. Each test wires a tiny Platform-like fixture (in-
memory stores, stub agent, real evaluator/critic/router) and asserts
one invariant.

  python -m unittest tests.core.decision_agents.test_atomic_tool
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.context_store import (  # noqa: E402
    ContextBuilder,
    ContextBundle,
    InMemoryDurableStore,
    InMemoryHotCache,
    LendingContextStore,
)
from core.context_store.base import Lineage  # noqa: E402
from core.decision_agents import (  # noqa: E402
    AgentReasoning,
    AtomicTool,
    DecisionAgent,
    DecisionAgentError,
    InMemoryHumanQueue,
    ModeRouter,
)
from core.decision_agents.mode_router import RouteAction  # noqa: E402
from core.knowledge import (  # noqa: E402
    ClaimRecord,
    DocumentRecord,
    KnowledgeStore,
    MetadataRetriever,
)
from core.normalizer.models import DecisionOutcome  # noqa: E402
from core.policy_engine import (  # noqa: E402
    PolicyEvaluator,
    PolicyRecord,
    PolicyStore,
    PolicyVersionRecord,
    UpstreamSummary,
)
from core.trace import (  # noqa: E402
    Contradiction,
    CriticAgent,
    CriticVerdict,
    InMemoryTraceWriter,
    SelfReviewError,
    Signal,
    SignalDirection,
    WorkJournalEntry,
)


# ─────────────────────────────────────────────────────────────────────
# Stub agent — scripted reasoning so we can drive each branch
# ─────────────────────────────────────────────────────────────────────


class StubAgent(DecisionAgent):
    """Returns a pre-set AgentReasoning. Lets us drive every branch
    of the atomic_tool without standing up real personas."""

    def __init__(
        self,
        *,
        decision_id: str,
        proposed_outcome: DecisionOutcome = DecisionOutcome.ALLOW,
        confidence: float = 0.95,
        output_payload: Optional[dict[str, Any]] = None,
        signal_count: int = 4,
        agent_id: str = "stub_agent",
        persona: str = "stub_persona",
        empty_hypothesis: bool = False,
    ):
        super().__init__(
            agent_id=agent_id,
            persona=persona,
            decision_id=decision_id,
        )
        self._proposed = proposed_outcome
        self._confidence = confidence
        self._payload = output_payload or {}
        self._signal_count = signal_count
        self._empty_hypothesis = empty_hypothesis

    async def reason(
        self,
        bundle: ContextBundle,
        policy=None,
    ) -> AgentReasoning:
        signals = [
            Signal(
                name=f"signal_{i}",
                value=i,
                direction=SignalDirection.SUPPORTS,
            )
            for i in range(self._signal_count)
        ]
        journal = WorkJournalEntry(
            hypothesis_tested="" if self._empty_hypothesis else "stub hypothesis",
            signals_evaluated=signals,
            contradictions_found=[],
            conclusion="stub conclusion",
            confidence_basis="stub basis",
            human_readable_summary="stub summary",
        )
        return AgentReasoning(
            journal=journal,
            proposed_outcome=self._proposed,
            confidence=self._confidence,
            output_payload=self._payload,
        )


# ─────────────────────────────────────────────────────────────────────
# Tiny Platform-like fixture
# ─────────────────────────────────────────────────────────────────────


def _spec(*decisions) -> dict:
    """Build a minimal spec from one or more decision dicts."""
    out = []
    for d in decisions:
        merged = {
            "id": d["id"],
            "name": d.get("name", d["id"]),
            "owner_team": "ops",
            "mode": "auto_execute",
            "risk_level": "medium",
            "boundary": {},
        }
        merged.update(d)
        out.append(merged)
    return {"domain": "test", "version": "0.1.0", "decisions": out}


def _decision_yaml(
    *,
    decision_id: str,
    boundary: Optional[dict] = None,
    mode: str = "auto_execute",
    risk_level: str = "medium",
    contamination_guard: Optional[dict] = None,
    depends_on: Optional[list[str]] = None,
) -> dict:
    d: dict[str, Any] = {
        "id": decision_id,
        "mode": mode,
        "risk_level": risk_level,
        "boundary": boundary or {"automate_if": ["score >= 0.5"]},
    }
    if contamination_guard:
        d["contamination_guard"] = contamination_guard
    if depends_on:
        d["depends_on"] = [
            {"decision": u, "required_output": "x"} for u in depends_on
        ]
    return d


def _build_fixture(
    *,
    decision_yaml: dict,
    use_policy_store: bool = False,
    use_knowledge: bool = False,
    critic: Optional[CriticAgent] = None,
):
    """Return a dict of components ready to construct an AtomicTool."""
    spec = _spec(decision_yaml)
    backing = LendingContextStore(InMemoryHotCache(), InMemoryDurableStore())

    knowledge_store = None
    retriever = None
    if use_knowledge:
        knowledge_store = KnowledgeStore(backing)
        # Empty matrix by default — tests opt into specific entries.
        retriever = MetadataRetriever(knowledge_store, doc_type_matrix={})

    builder = ContextBuilder(backing, spec, retriever=retriever)
    evaluator = PolicyEvaluator(spec)
    policy_store = PolicyStore(backing) if use_policy_store else None

    queue = InMemoryHumanQueue()
    router = ModeRouter(backing, queue)
    trace_writer = InMemoryTraceWriter()

    tool = AtomicTool(
        builder=builder,
        evaluator=evaluator,
        critic=critic,
        trace_writer=trace_writer,
        router=router,
        policy_store=policy_store,
    )

    return {
        "spec": spec,
        "backing": backing,
        "builder": builder,
        "evaluator": evaluator,
        "policy_store": policy_store,
        "knowledge_store": knowledge_store,
        "retriever": retriever,
        "queue": queue,
        "router": router,
        "trace_writer": trace_writer,
        "tool": tool,
    }


async def _trivial_resolver(_object_type_id: str, _application_id: str) -> list[str]:
    return []


async def _seed_policy_version(
    store: PolicyStore,
    *,
    decision_id: str,
    agency: str = "lender_overlay",
    boundary: Optional[dict] = None,
    contamination_guard: Optional[dict] = None,
):
    policy_id = f"{agency}::{decision_id}"
    version_id = f"{policy_id}::v1"
    await store.put_policy(PolicyRecord(
        policy_id=policy_id,
        name="seeded",
        owner_team="ops",
        agency=agency,
        decision_id=decision_id,
    ))
    await store.put_policy_version(PolicyVersionRecord(
        policy_version_id=version_id,
        policy_id=policy_id,
        version_number=1,
        valid_from=datetime(2020, 1, 1),
        boundary=boundary or {"automate_if": ["score >= 0.5"]},
        contamination_guard=contamination_guard,
        ingested_at=datetime(2026, 1, 1),
    ))
    return version_id


# ─────────────────────────────────────────────────────────────────────
# Happy path + core invariants
# ─────────────────────────────────────────────────────────────────────


class HappyPathTests(unittest.IsolatedAsyncioTestCase):

    async def test_writes_trace_and_routes_auto_writeback(self):
        f = _build_fixture(decision_yaml=_decision_yaml(
            decision_id="d1",
            boundary={"automate_if": ["score >= 0.5"]},
        ))
        agent = StubAgent(
            decision_id="d1",
            proposed_outcome=DecisionOutcome.ALLOW,
            output_payload={"score": 0.9},
        )
        result = await f["tool"].run(
            agent, application_id="app1", resolver=_trivial_resolver
        )
        self.assertEqual(result.final_outcome, DecisionOutcome.ALLOW)
        self.assertEqual(result.routed.action, RouteAction.AUTO_WRITEBACK)
        # Trace persisted.
        traces = list(f["trace_writer"]._traces.values())
        self.assertEqual(len(traces), 1)
        self.assertEqual(traces[0].outcome, DecisionOutcome.ALLOW)


class PolicyOverridesAgentTests(unittest.IsolatedAsyncioTestCase):

    async def test_policy_block_wins_when_agent_proposes_allow(self):
        # The boundary forces BLOCK on score >= 0.9; the agent
        # disagrees and proposes ALLOW. Policy wins.
        f = _build_fixture(decision_yaml=_decision_yaml(
            decision_id="d1",
            boundary={"block_if": ["score >= 0.9"]},
        ))
        agent = StubAgent(
            decision_id="d1",
            proposed_outcome=DecisionOutcome.ALLOW,
            output_payload={"score": 0.95},
        )
        result = await f["tool"].run(
            agent, application_id="app1", resolver=_trivial_resolver
        )
        self.assertEqual(result.final_outcome, DecisionOutcome.BLOCK)


# ─────────────────────────────────────────────────────────────────────
# Hard rules + contamination
# ─────────────────────────────────────────────────────────────────────


class HardRuleAndContaminationTests(unittest.IsolatedAsyncioTestCase):

    async def test_fraud_block_propagates_to_dependent(self):
        f = _build_fixture(decision_yaml=_decision_yaml(
            decision_id="ltv_assessment",
            boundary={"automate_if": ["score >= 0.5"]},
            depends_on=["fraud_screening"],
        ))
        agent = StubAgent(
            decision_id="ltv_assessment",
            proposed_outcome=DecisionOutcome.ALLOW,
            output_payload={"score": 0.9},
        )
        result = await f["tool"].run(
            agent,
            application_id="app1",
            resolver=_trivial_resolver,
            upstream=[
                UpstreamSummary(
                    decision_id="fraud_screening",
                    outcome="block",  # type: ignore[arg-type]
                    confidence=0.95,
                ),
            ],
        )
        self.assertEqual(result.final_outcome, DecisionOutcome.BLOCK)
        # The trace's policy_reasons names the specific rule.
        traces = list(f["trace_writer"]._traces.values())
        self.assertTrue(any(
            "fraud_block_stops_pipeline" in r
            for r in (traces[0].policy_reasons or [])
        ))

    async def test_contamination_guard_marks_trace(self):
        f = _build_fixture(decision_yaml=_decision_yaml(
            decision_id="dti_calculation",
            boundary={"automate_if": ["score >= 0.5"]},
            contamination_guard={"reject_if_upstream_confidence_below": 0.75},
            depends_on=["income_verification"],
        ))
        agent = StubAgent(
            decision_id="dti_calculation",
            proposed_outcome=DecisionOutcome.ALLOW,
            output_payload={"score": 0.9},
        )
        result = await f["tool"].run(
            agent,
            application_id="app1",
            resolver=_trivial_resolver,
            upstream=[
                UpstreamSummary(
                    decision_id="income_verification",
                    outcome="recommend",  # type: ignore[arg-type]
                    confidence=0.50,
                ),
            ],
        )
        self.assertEqual(result.final_outcome, DecisionOutcome.BLOCK)
        traces = list(f["trace_writer"]._traces.values())
        self.assertTrue(traces[0].contamination)


# ─────────────────────────────────────────────────────────────────────
# Critic + SelfReviewError
# ─────────────────────────────────────────────────────────────────────


class CriticTests(unittest.IsolatedAsyncioTestCase):

    async def test_critic_runs_on_medium_risk(self):
        f = _build_fixture(
            decision_yaml=_decision_yaml(
                decision_id="d1",
                risk_level="medium",
                boundary={"automate_if": ["score >= 0.5"]},
            ),
            critic=CriticAgent(critic_id="critic_v1"),
        )
        agent = StubAgent(
            decision_id="d1",
            proposed_outcome=DecisionOutcome.ALLOW,
            output_payload={"score": 0.9},
            signal_count=5,
        )
        result = await f["tool"].run(
            agent, application_id="app1", resolver=_trivial_resolver
        )
        self.assertIsNotNone(result.critic_review)
        # Trace too.
        traces = list(f["trace_writer"]._traces.values())
        self.assertIsNotNone(traces[0].critic_review)

    async def test_critic_skipped_on_low_risk(self):
        f = _build_fixture(
            decision_yaml=_decision_yaml(
                decision_id="d1",
                risk_level="low",
                boundary={"automate_if": ["score >= 0.5"]},
            ),
            critic=CriticAgent(
                critic_id="critic_v1",
                # Default target = (MEDIUM,); low risk is out of scope.
            ),
        )
        agent = StubAgent(
            decision_id="d1",
            proposed_outcome=DecisionOutcome.ALLOW,
            output_payload={"score": 0.9},
        )
        result = await f["tool"].run(
            agent, application_id="app1", resolver=_trivial_resolver
        )
        self.assertIsNone(result.critic_review)

    async def test_self_review_error_reraises(self):
        critic = CriticAgent(critic_id="same_id_for_both")
        f = _build_fixture(
            decision_yaml=_decision_yaml(
                decision_id="d1",
                risk_level="medium",
                boundary={"automate_if": ["score >= 0.5"]},
            ),
            critic=critic,
        )
        # Agent uses the same id as the critic — self-review.
        agent = StubAgent(
            decision_id="d1",
            agent_id="same_id_for_both",
            proposed_outcome=DecisionOutcome.ALLOW,
            output_payload={"score": 0.9},
        )
        with self.assertRaises(SelfReviewError):
            await f["tool"].run(
                agent, application_id="app1", resolver=_trivial_resolver
            )


# ─────────────────────────────────────────────────────────────────────
# PolicyStore stamping
# ─────────────────────────────────────────────────────────────────────


class PolicyStoreStampingTests(unittest.IsolatedAsyncioTestCase):

    async def test_no_stamp_without_policy_store(self):
        f = _build_fixture(decision_yaml=_decision_yaml(
            decision_id="d1",
            boundary={"automate_if": ["score >= 0.5"]},
        ))
        agent = StubAgent(
            decision_id="d1",
            proposed_outcome=DecisionOutcome.ALLOW,
            output_payload={"score": 0.9},
        )
        result = await f["tool"].run(
            agent, application_id="app1", resolver=_trivial_resolver
        )
        traces = list(f["trace_writer"]._traces.values())
        self.assertIsNone(traces[0].policy_version_id)
        self.assertEqual(traces[0].policy_chain, [])

    async def test_stamp_set_when_store_wired(self):
        f = _build_fixture(
            decision_yaml=_decision_yaml(
                decision_id="d1",
                boundary={"automate_if": ["score >= 0.99"]},  # not used
            ),
            use_policy_store=True,
        )
        version_id = await _seed_policy_version(
            f["policy_store"],
            decision_id="d1",
            boundary={"automate_if": ["score >= 0.5"]},
        )
        agent = StubAgent(
            decision_id="d1",
            proposed_outcome=DecisionOutcome.ALLOW,
            output_payload={"score": 0.9},
        )
        result = await f["tool"].run(
            agent, application_id="app1", resolver=_trivial_resolver
        )
        self.assertEqual(result.final_outcome, DecisionOutcome.ALLOW)
        traces = list(f["trace_writer"]._traces.values())
        self.assertEqual(traces[0].policy_version_id, version_id)
        self.assertEqual(traces[0].policy_chain, [version_id])


# ─────────────────────────────────────────────────────────────────────
# agency_chain derivation
# ─────────────────────────────────────────────────────────────────────


class AgencyChainTests(unittest.IsolatedAsyncioTestCase):

    async def _seed_loan(self, backing: LendingContextStore, *, loan_type: str):
        await backing.set(
            "Loan",
            "loan-app1",
            {"loan_id": "loan-app1", "application_id": "app1", "loan_type": loan_type},
            Lineage(written_by="test", decision_id=None),
        )

    async def _resolver_for_loan(self) -> Any:
        async def _resolve(object_type_id: str, application_id: str) -> list[str]:
            if object_type_id == "Loan":
                return ["loan-app1"]
            return []
        return _resolve

    async def test_chain_derived_from_loan_type_when_caller_omits(self):
        # decision must be allowed to read Loan via decisions_that_read_it
        # in the ontology — ltv_assessment IS in that list.
        f = _build_fixture(
            decision_yaml=_decision_yaml(
                decision_id="ltv_assessment",
                boundary={"automate_if": ["score >= 0.5"]},
            ),
            use_policy_store=True,
        )
        # Seed an FHA-specific PolicyVersion for ltv_assessment so the
        # chain has a 2nd entry to capture.
        overlay = await _seed_policy_version(
            f["policy_store"],
            decision_id="ltv_assessment",
            agency="lender_overlay",
            boundary={"automate_if": ["score >= 0.5"]},
        )
        fha = await _seed_policy_version(
            f["policy_store"],
            decision_id="ltv_assessment",
            agency="fha",
            boundary={"automate_if": ["score >= 0.5"]},
        )
        await self._seed_loan(f["backing"], loan_type="fha")
        resolver = await self._resolver_for_loan()

        agent = StubAgent(
            decision_id="ltv_assessment",
            proposed_outcome=DecisionOutcome.ALLOW,
            output_payload={"score": 0.9},
        )
        result = await f["tool"].run(
            agent, application_id="app1", resolver=resolver
        )
        traces = list(f["trace_writer"]._traces.values())
        self.assertEqual(traces[0].policy_chain, [overlay, fha])

    async def test_explicit_chain_wins_over_derived(self):
        f = _build_fixture(
            decision_yaml=_decision_yaml(
                decision_id="ltv_assessment",
                boundary={"automate_if": ["score >= 0.5"]},
            ),
            use_policy_store=True,
        )
        overlay = await _seed_policy_version(
            f["policy_store"],
            decision_id="ltv_assessment",
            agency="lender_overlay",
            boundary={"automate_if": ["score >= 0.5"]},
        )
        # Loan has loan_type=fha (would derive [overlay, fha]) but
        # caller passes only [lender_overlay] → chain stays single-entry.
        await self._seed_loan(f["backing"], loan_type="fha")
        resolver = await self._resolver_for_loan()

        agent = StubAgent(
            decision_id="ltv_assessment",
            proposed_outcome=DecisionOutcome.ALLOW,
            output_payload={"score": 0.9},
        )
        result = await f["tool"].run(
            agent,
            application_id="app1",
            resolver=resolver,
            agency_chain=["lender_overlay"],
        )
        traces = list(f["trace_writer"]._traces.values())
        self.assertEqual(traces[0].policy_chain, [overlay])


# ─────────────────────────────────────────────────────────────────────
# Claim-aware boundary evaluation
# ─────────────────────────────────────────────────────────────────────


class ClaimAwareBoundaryTests(unittest.IsolatedAsyncioTestCase):

    async def test_claim_value_satisfies_boundary(self):
        # Boundary references a field that the agent does NOT compute
        # itself; a verified claim provides it via bundle.claims, and
        # the policy engine reads it through _policy_context.
        f = _build_fixture(
            decision_yaml=_decision_yaml(
                decision_id="income_verification",
                boundary={"automate_if": ["verified_income >= 100000"]},
            ),
            use_knowledge=True,
        )
        # Wire the matrix entry so the retriever knows W-2 feeds
        # income_verification.
        f["retriever"] = MetadataRetriever(
            f["knowledge_store"],
            doc_type_matrix={
                "w2": {
                    "feeds_decisions": ["income_verification"],
                    "claims": ["verified_income"],
                },
            },
        )
        # Rebuild the builder with the new retriever.
        f["builder"] = ContextBuilder(
            f["backing"], f["spec"], retriever=f["retriever"]
        )
        f["tool"] = AtomicTool(
            builder=f["builder"],
            evaluator=f["evaluator"],
            critic=None,
            trace_writer=f["trace_writer"],
            router=f["router"],
            policy_store=f["policy_store"],
        )
        # Seed a verified W-2 + claim.
        await f["knowledge_store"].put_document(DocumentRecord(
            document_id="doc1",
            application_id="app1",
            applicant_id="cust1",
            doc_type="w2",
            status="verified",
        ))
        await f["knowledge_store"].put_claim(ClaimRecord(
            claim_id="c1",
            document_id="doc1",
            application_id="app1",
            applicant_id="cust1",
            field_name="verified_income",
            field_value=124500,
            status="verified",
            extracted_at=datetime(2026, 4, 1),
        ))
        # Agent doesn't compute verified_income; the claim must drive
        # the boundary check.
        agent = StubAgent(
            decision_id="income_verification",
            proposed_outcome=DecisionOutcome.ALLOW,
            output_payload={},  # no score, no verified_income
        )
        result = await f["tool"].run(
            agent, application_id="app1", resolver=_trivial_resolver
        )
        self.assertEqual(result.final_outcome, DecisionOutcome.ALLOW)


# ─────────────────────────────────────────────────────────────────────
# Reasoning validation
# ─────────────────────────────────────────────────────────────────────


class ReasoningValidationTests(unittest.IsolatedAsyncioTestCase):

    async def test_empty_hypothesis_raises_decision_agent_error(self):
        f = _build_fixture(decision_yaml=_decision_yaml(
            decision_id="d1",
            boundary={"automate_if": ["score >= 0.5"]},
        ))
        agent = StubAgent(
            decision_id="d1",
            proposed_outcome=DecisionOutcome.ALLOW,
            output_payload={"score": 0.9},
            empty_hypothesis=True,
        )
        with self.assertRaises(DecisionAgentError):
            await f["tool"].run(
                agent, application_id="app1", resolver=_trivial_resolver
            )


# ─────────────────────────────────────────────────────────────────────
# Routing
# ─────────────────────────────────────────────────────────────────────


class RoutingTests(unittest.IsolatedAsyncioTestCase):

    async def test_human_approval_mode_routes_to_queue(self):
        f = _build_fixture(decision_yaml=_decision_yaml(
            decision_id="d1",
            mode="human_approval",
            boundary={"automate_if": ["score >= 0.5"]},
        ))
        agent = StubAgent(
            decision_id="d1",
            proposed_outcome=DecisionOutcome.ALLOW,
            output_payload={"score": 0.9},
        )
        result = await f["tool"].run(
            agent, application_id="app1", resolver=_trivial_resolver
        )
        self.assertEqual(result.routed.action, RouteAction.QUEUE_HUMAN)
        self.assertEqual(len(f["queue"]._items), 1)

    async def test_block_writes_decision_record_for_propagation(self):
        f = _build_fixture(decision_yaml=_decision_yaml(
            decision_id="d1",
            boundary={"block_if": ["score >= 0.5"]},
        ))
        agent = StubAgent(
            decision_id="d1",
            proposed_outcome=DecisionOutcome.ALLOW,
            output_payload={"score": 0.9},
        )
        result = await f["tool"].run(
            agent, application_id="app1", resolver=_trivial_resolver
        )
        self.assertEqual(result.routed.action, RouteAction.BLOCK)
        # Decision record persisted so dependents can read the block.
        durable = f["backing"]._durable
        decision_records = [
            r for r in durable._records
            if r.entity_type == "decision"
        ]
        self.assertEqual(len(decision_records), 1)


# ─────────────────────────────────────────────────────────────────────
# HumanQueue.resolve()
# ─────────────────────────────────────────────────────────────────────


class HumanQueueResolveTests(unittest.IsolatedAsyncioTestCase):

    async def test_resolve_removes_open_item_and_records_receipt(self):
        from uuid import uuid4
        f = _build_fixture(decision_yaml=_decision_yaml(
            decision_id="d1",
            mode="human_approval",
            boundary={"automate_if": ["score >= 0.5"]},
        ))
        agent = StubAgent(
            decision_id="d1",
            proposed_outcome=DecisionOutcome.ALLOW,
            output_payload={"score": 0.9},
        )
        # Run the atomic tool to enqueue an item.
        await f["tool"].run(
            agent, application_id="app1", resolver=_trivial_resolver
        )
        self.assertEqual(len(f["queue"]._items), 1)

        item = next(iter(f["queue"]._items.values()))
        receipt = await f["queue"].resolve(
            item.id,
            resolution="approve",
            reviewer_id="bgoud",
            reviewer_role="underwriter",
        )
        self.assertIsNotNone(receipt)
        self.assertEqual(receipt.resolution, "approve")
        self.assertEqual(len(f["queue"]._items), 0)
        resolved = await f["queue"].list_resolved()
        self.assertEqual(len(resolved), 1)

    async def test_resolve_unknown_id_returns_none(self):
        from uuid import uuid4
        f = _build_fixture(decision_yaml=_decision_yaml(
            decision_id="d1",
            boundary={"automate_if": ["score >= 0.5"]},
        ))
        receipt = await f["queue"].resolve(
            uuid4(),
            resolution="approve",
            reviewer_id="x",
            reviewer_role="y",
        )
        self.assertIsNone(receipt)

    async def test_find_open_returns_matching_item(self):
        f = _build_fixture(decision_yaml=_decision_yaml(
            decision_id="d1",
            mode="human_approval",
            boundary={"automate_if": ["score >= 0.5"]},
        ))
        agent = StubAgent(
            decision_id="d1",
            proposed_outcome=DecisionOutcome.ALLOW,
            output_payload={"score": 0.9},
        )
        await f["tool"].run(
            agent, application_id="appA", resolver=_trivial_resolver
        )
        found = await f["queue"].find_open(
            application_id="appA", decision_id="d1"
        )
        self.assertIsNotNone(found)
        # Wrong app — None.
        miss = await f["queue"].find_open(
            application_id="appB", decision_id="d1"
        )
        self.assertIsNone(miss)


if __name__ == "__main__":
    unittest.main()

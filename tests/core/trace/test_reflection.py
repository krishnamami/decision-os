"""ReflectionService tests — capture/recall/retention.

  python -m unittest tests.core.trace.test_reflection
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.normalizer.models import DecisionMode, DecisionOutcome, RiskLevel  # noqa: E402
from core.trace import (  # noqa: E402
    AgentLearning,
    DecisionTrace,
    HumanReview,
    InMemoryLearningStore,
    ReflectionService,
    SignalDirection,
    WorkJournalEntry,
    derive_similarity_tags,
)


def _trace(
    *,
    decision_id: str = "credit_assessment",
    persona: str = "credit_risk_agent",
    agent_id: str = "credit_risk_agent_v1",
    outcome: DecisionOutcome = DecisionOutcome.RECOMMEND,
    confidence: float = 0.7,
    payload: dict | None = None,
) -> DecisionTrace:
    return DecisionTrace(
        decision_id=decision_id,
        application_id="app_test",
        agent_id=agent_id,
        persona=persona,
        mode=DecisionMode.AUTO_EXECUTE,
        risk_level=RiskLevel.MEDIUM,
        inputs_snapshot_id=uuid4(),
        reasoning=WorkJournalEntry(
            hypothesis_tested="seeded for reflection test",
            signals_evaluated=[],
            contradictions_found=[],
            conclusion="seeded",
            confidence_basis="seeded",
            human_readable_summary="seeded",
        ),
        outcome=outcome,
        confidence=confidence,
        output_payload=payload or {},
    )


def _review(
    *,
    original: DecisionOutcome = DecisionOutcome.RECOMMEND,
    final: DecisionOutcome = DecisionOutcome.BLOCK,
    overridden: bool = True,
    reviewer_role: str = "underwriter",
    reason: str = "documented downside risk",
    code: str | None = "manual_decline",
) -> HumanReview:
    return HumanReview(
        reviewer_id="bgoud",
        reviewer_role=reviewer_role,
        original_ai_decision=original,
        final_outcome=final,
        overridden=overridden,
        override_reason=reason,
        override_reason_code=code,
    )


class CaptureValidationTests(unittest.IsolatedAsyncioTestCase):

    async def test_rejects_non_override(self):
        store = InMemoryLearningStore()
        svc = ReflectionService(store)
        trace = _trace()
        review = _review(overridden=False)
        with self.assertRaises(ValueError):
            await svc.capture(trace, review)

    async def test_rejects_when_original_equals_final(self):
        # An ack stamped as overridden=True but with the same outcome
        # is a noise lesson — refused at the boundary.
        store = InMemoryLearningStore()
        svc = ReflectionService(store)
        trace = _trace()
        review = _review(
            original=DecisionOutcome.RECOMMEND,
            final=DecisionOutcome.RECOMMEND,
        )
        with self.assertRaises(ValueError):
            await svc.capture(trace, review)

    async def test_capture_writes_record(self):
        store = InMemoryLearningStore()
        svc = ReflectionService(store)
        trace = _trace()
        review = _review()
        learning = await svc.capture(trace, review)
        self.assertIsInstance(learning, AgentLearning)
        self.assertEqual(learning.agent_id, trace.agent_id)
        self.assertEqual(learning.decision_id, trace.decision_id)
        # Persisted.
        again = await store.get(learning.agent_learning_id)
        self.assertEqual(again, learning)


class TaggingTests(unittest.IsolatedAsyncioTestCase):

    async def test_capture_auto_tags_role_code_decision(self):
        store = InMemoryLearningStore()
        svc = ReflectionService(store)
        trace = _trace()
        review = _review(
            reviewer_role="senior_underwriter",
            code="risk_layering",
        )
        learning = await svc.capture(trace, review)
        tags = set(learning.similarity_tags)
        self.assertIn("senior_underwriter", tags)
        self.assertIn("risk_layering", tags)
        self.assertIn(trace.decision_id, tags)

    async def test_capture_appends_to_caller_tags(self):
        store = InMemoryLearningStore()
        svc = ReflectionService(store)
        trace = _trace()
        review = _review(reviewer_role="compliance", code=None)
        learning = await svc.capture(
            trace, review, similarity_tags=["loan_type:jumbo", "state:CA"]
        )
        tags = set(learning.similarity_tags)
        self.assertIn("loan_type:jumbo", tags)
        self.assertIn("state:CA", tags)
        self.assertIn("compliance", tags)
        self.assertIn(trace.decision_id, tags)


class RecallRankingTests(unittest.IsolatedAsyncioTestCase):

    async def test_recall_ranks_by_tag_overlap(self):
        store = InMemoryLearningStore()
        svc = ReflectionService(store)
        trace = _trace()
        # Three captures: a, b, c with different tag overlap with our query.
        await svc.capture(
            trace, _review(reviewer_role="role_a", code="reason_a"),
            similarity_tags=["loan_type:jumbo"],
        )
        await svc.capture(
            trace, _review(reviewer_role="role_b", code="reason_b"),
            similarity_tags=["loan_type:fha", "state:CA"],
        )
        await svc.capture(
            trace, _review(reviewer_role="role_c", code="reason_c"),
            similarity_tags=["loan_type:jumbo", "state:CA"],
        )
        # Query with both jumbo + CA → c overlaps most.
        results = await svc.recall(
            trace.agent_id,
            trace.decision_id,
            similarity_tags=["loan_type:jumbo", "state:CA"],
        )
        self.assertGreater(len(results), 0)
        self.assertEqual(results[0].similarity_tags[:1], ["loan_type:jumbo"])
        self.assertIn("loan_type:jumbo", results[0].similarity_tags)
        self.assertIn("state:CA", results[0].similarity_tags)

    async def test_recall_filters_expired(self):
        store = InMemoryLearningStore()
        svc = ReflectionService(store, retention_days=365)
        trace = _trace()
        # Manually write a record that's already expired.
        expired = AgentLearning(
            agent_id=trace.agent_id,
            persona=trace.persona,
            decision_id=trace.decision_id,
            trace_id=trace.trace_id,
            original_ai_decision=DecisionOutcome.RECOMMEND,
            human_decision=DecisionOutcome.BLOCK,
            override_reason="historical",
            reviewer_role="underwriter",
            lesson="historical lesson",
            similarity_tags=[trace.decision_id],
            captured_at=datetime.utcnow() - timedelta(days=400),
            expires_at=datetime.utcnow() - timedelta(days=1),
        )
        await store.write(expired)
        # Capture a fresh one.
        fresh = await svc.capture(trace, _review())
        results = await svc.recall(trace.agent_id, trace.decision_id)
        ids = {r.agent_learning_id for r in results}
        self.assertIn(fresh.agent_learning_id, ids)
        self.assertNotIn(expired.agent_learning_id, ids)

    async def test_recall_limit(self):
        store = InMemoryLearningStore()
        svc = ReflectionService(store)
        trace = _trace()
        for i in range(8):
            await svc.capture(
                trace,
                _review(reviewer_role=f"role_{i}", code=f"code_{i}"),
            )
        results = await svc.recall(trace.agent_id, trace.decision_id, limit=3)
        self.assertEqual(len(results), 3)


class RetentionTests(unittest.IsolatedAsyncioTestCase):

    async def test_retention_days_must_be_positive(self):
        store = InMemoryLearningStore()
        with self.assertRaises(ValueError):
            ReflectionService(store, retention_days=0)
        with self.assertRaises(ValueError):
            ReflectionService(store, retention_days=-1)

    async def test_prune_expired_removes_old_records(self):
        store = InMemoryLearningStore()
        svc = ReflectionService(store, retention_days=365)
        trace = _trace()
        await svc.capture(trace, _review())
        # Manually inject an expired record.
        expired = AgentLearning(
            agent_id=trace.agent_id,
            persona=trace.persona,
            decision_id=trace.decision_id,
            trace_id=trace.trace_id,
            original_ai_decision=DecisionOutcome.RECOMMEND,
            human_decision=DecisionOutcome.BLOCK,
            override_reason="historical",
            reviewer_role="underwriter",
            lesson="historical",
            similarity_tags=[trace.decision_id],
            captured_at=datetime.utcnow() - timedelta(days=400),
            expires_at=datetime.utcnow() - timedelta(days=1),
        )
        await store.write(expired)
        before = len(store)
        pruned = await svc.prune_expired()
        after = len(store)
        self.assertEqual(pruned, 1)
        self.assertEqual(after, before - 1)


class DeriveTagsTests(unittest.TestCase):

    def test_extracts_known_payload_fields(self):
        trace = _trace(payload={
            "employment_type": "self_employed",
            "credit_band": "near_prime",
            "loan_purpose": "purchase",
            "loan_type": "fha",
            "irrelevant_field": 42,
        })
        tags = derive_similarity_tags(trace)
        self.assertIn(trace.decision_id, tags)
        self.assertIn(trace.persona, tags)
        self.assertIn("employment_type:self_employed", tags)
        self.assertIn("credit_band:near_prime", tags)
        self.assertIn("loan_purpose:purchase", tags)
        self.assertIn("loan_type:fha", tags)

    def test_skips_non_string_values(self):
        trace = _trace(payload={
            "credit_band": "prime",
            "credit_score": 740,        # int — not tagged
            "approved": True,           # bool — not tagged
        })
        tags = derive_similarity_tags(trace)
        self.assertIn("credit_band:prime", tags)
        for t in tags:
            self.assertFalse(t.startswith("credit_score:"))
            self.assertFalse(t.startswith("approved:"))


class StoreContractTests(unittest.IsolatedAsyncioTestCase):

    async def test_duplicate_id_rejected(self):
        store = InMemoryLearningStore()
        svc = ReflectionService(store)
        trace = _trace()
        learning = await svc.capture(trace, _review())
        # Re-writing the same record with the same id raises.
        with self.assertRaises(ValueError):
            await store.write(learning)

    async def test_list_for_agent_filters(self):
        store = InMemoryLearningStore()
        svc = ReflectionService(store)
        trace_a = _trace(agent_id="agent_a", decision_id="d1")
        trace_b = _trace(agent_id="agent_b", decision_id="d1")
        await svc.capture(trace_a, _review())
        await svc.capture(trace_b, _review())
        result = await store.list_for_agent("agent_a", "d1")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].agent_id, "agent_a")


if __name__ == "__main__":
    unittest.main()

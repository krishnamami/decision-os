"""Audit Engine tests — schema, four checkers, engine fan-out, store.

  python -m unittest tests.core.audit.test_engine
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.audit import (  # noqa: E402
    AccessRecord,
    AuditEngine,
    AuditRecord,
    CheckStatus,
    ComplianceChecker,
    ConsentStatus,
    DataClassification,
    EncryptionStatus,
    EthicsChecker,
    FairnessChecker,
    InMemoryAuditStore,
    SecurityChecker,
)
from core.normalizer.models import DecisionMode, DecisionOutcome, RiskLevel  # noqa: E402
from core.trace import DecisionTrace, WorkJournalEntry  # noqa: E402


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _trace(
    *,
    decision_id: str = "credit_assessment",
    outcome: DecisionOutcome = DecisionOutcome.ALLOW,
    confidence: float = 0.85,
    policy_version_id: str | None = "policy:credit_assessment:v1",
) -> DecisionTrace:
    return DecisionTrace(
        decision_id=decision_id,
        application_id="app_audit_test",
        agent_id="credit_risk_agent_v1",
        persona="credit_risk_agent",
        mode=DecisionMode.AUTO_EXECUTE,
        risk_level=RiskLevel.MEDIUM,
        inputs_snapshot_id=uuid4(),
        reasoning=WorkJournalEntry(
            hypothesis_tested="x",
            conclusion="x",
            confidence_basis="x",
            human_readable_summary="x",
        ),
        outcome=outcome,
        confidence=confidence,
        policy_version_id=policy_version_id,
        policy_matched_clause="recommend_if",
        policy_decision_outcome=outcome,
    )


# ─────────────────────────────────────────────────────────────────────
# Schema
# ─────────────────────────────────────────────────────────────────────


class SchemaTests(unittest.TestCase):
    def test_audit_record_minimal_construction(self):
        record = AuditRecord(
            decision_id=uuid4(),
            application_id="app_1",
            decision_type="credit_assessment",
            decision_output=DecisionOutcome.ALLOW,
            confidence=0.9,
            owner="credit_risk_agent",
            mode=DecisionMode.AUTO_EXECUTE,
        )
        self.assertEqual(record.compliance_status, CheckStatus.PASS)
        self.assertEqual(record.overall_status, CheckStatus.PASS)
        self.assertEqual(record.consent_status, ConsentStatus.OBTAINED)
        self.assertEqual(record.data_classification, DataClassification.CONFIDENTIAL)
        self.assertEqual(record.encryption_status, EncryptionStatus.BOTH)


# ─────────────────────────────────────────────────────────────────────
# Compliance checker
# ─────────────────────────────────────────────────────────────────────


class ComplianceCheckerTests(unittest.TestCase):
    def setUp(self):
        self.checker = ComplianceChecker()

    def _record(self, **overrides) -> AuditRecord:
        defaults: dict = dict(
            decision_id=uuid4(),
            application_id="app_1",
            decision_type="credit_assessment",
            decision_output=DecisionOutcome.ALLOW,
            confidence=0.9,
            owner="credit_risk_agent",
            mode=DecisionMode.AUTO_EXECUTE,
            regulation_tags=["FCRA", "ECOA"],
        )
        defaults.update(overrides)
        return AuditRecord(**defaults)

    def test_pass_when_tags_and_consent_present(self):
        result = self.checker.check(self._record())
        self.assertEqual(result.status, CheckStatus.PASS)
        self.assertEqual(result.findings, [])

    def test_warn_on_missing_required_tag(self):
        result = self.checker.check(self._record(regulation_tags=["FCRA"]))
        self.assertEqual(result.status, CheckStatus.WARN)
        self.assertTrue(any("ECOA" in f for f in result.findings))

    def test_fail_on_missing_consent(self):
        result = self.checker.check(
            self._record(consent_status=ConsentStatus.MISSING)
        )
        self.assertEqual(result.status, CheckStatus.FAIL)

    def test_fail_on_withdrawn_consent(self):
        result = self.checker.check(
            self._record(consent_status=ConsentStatus.WITHDRAWN)
        )
        self.assertEqual(result.status, CheckStatus.FAIL)

    def test_fail_on_trid_without_disclosure(self):
        result = self.checker.check(
            self._record(
                decision_type="closing_readiness",
                regulation_tags=["TRID", "RESPA"],
                disclosure_sent=False,
            )
        )
        self.assertEqual(result.status, CheckStatus.FAIL)

    def test_warn_when_credit_bureau_used_without_fcra_tag(self):
        # ECOA is the default for dti_calculation; FCRA is not.
        result = self.checker.check(
            self._record(
                decision_type="dti_calculation",
                regulation_tags=["ECOA"],
                data_sources_used=["credit_bureau"],
            )
        )
        self.assertEqual(result.status, CheckStatus.WARN)


# ─────────────────────────────────────────────────────────────────────
# Security checker
# ─────────────────────────────────────────────────────────────────────


class SecurityCheckerTests(unittest.TestCase):
    def setUp(self):
        self.checker = SecurityChecker(velocity_threshold=3, velocity_window_seconds=60)

    def _record(self, **overrides) -> AuditRecord:
        defaults: dict = dict(
            decision_id=uuid4(),
            application_id="app_1",
            decision_type="credit_assessment",
            decision_output=DecisionOutcome.ALLOW,
            confidence=0.9,
            owner="credit_risk_agent",
            mode=DecisionMode.AUTO_EXECUTE,
        )
        defaults.update(overrides)
        return AuditRecord(**defaults)

    def test_pass_with_proper_permissions(self):
        record = self._record(
            pii_fields_accessed=["ssn"],
            permissions_used=["credit_pull"],
        )
        result = self.checker.check(record)
        self.assertEqual(result.status, CheckStatus.PASS)

    def test_fail_when_pii_accessed_without_permissions(self):
        record = self._record(
            pii_fields_accessed=["ssn"],
            permissions_used=[],
        )
        result = self.checker.check(record)
        self.assertEqual(result.status, CheckStatus.FAIL)

    def test_warn_on_velocity_anomaly(self):
        base = datetime.utcnow()
        accessed = [
            AccessRecord(
                user_id="ops_alice",
                role="ops",
                action="read",
                timestamp=base + timedelta(seconds=i),
            )
            for i in range(5)
        ]
        result = self.checker.check(self._record(accessed_by=accessed))
        self.assertEqual(result.status, CheckStatus.WARN)
        self.assertTrue(any("velocity" in f for f in result.findings))

    def test_warn_when_restricted_data_partially_encrypted(self):
        record = self._record(
            data_classification=DataClassification.RESTRICTED,
            encryption_status=EncryptionStatus.AT_REST,
        )
        result = self.checker.check(record)
        self.assertEqual(result.status, CheckStatus.WARN)


# ─────────────────────────────────────────────────────────────────────
# Ethics checker
# ─────────────────────────────────────────────────────────────────────


class EthicsCheckerTests(unittest.TestCase):
    def setUp(self):
        self.checker = EthicsChecker()

    def _record(self, **overrides) -> AuditRecord:
        defaults: dict = dict(
            decision_id=uuid4(),
            application_id="app_1",
            decision_type="credit_assessment",
            decision_output=DecisionOutcome.ALLOW,
            confidence=0.9,
            owner="credit_risk_agent",
            mode=DecisionMode.AUTO_EXECUTE,
            protected_attrs_excluded=["race", "sex", "national_origin"],
        )
        defaults.update(overrides)
        return AuditRecord(**defaults)

    def test_pass_with_protected_attrs_excluded(self):
        result = self.checker.check(self._record())
        self.assertEqual(result.status, CheckStatus.PASS)

    def test_fail_when_protected_attribute_used_without_exclusion(self):
        record = self._record(
            protected_attrs_used=["race"],
            protected_attrs_excluded=[],
        )
        result = self.checker.check(record)
        self.assertEqual(result.status, CheckStatus.FAIL)
        self.assertEqual(len(record.fairness_flags), 1)

    def test_warn_at_monitoring_bias_threshold(self):
        result = self.checker.check(self._record(bias_score=0.20))
        self.assertEqual(result.status, CheckStatus.WARN)

    def test_fail_at_action_bias_threshold(self):
        result = self.checker.check(self._record(bias_score=0.31))
        self.assertEqual(result.status, CheckStatus.FAIL)

    def test_warn_on_disparate_impact_flag(self):
        result = self.checker.check(self._record(disparate_impact_flag=True))
        self.assertEqual(result.status, CheckStatus.WARN)


# ─────────────────────────────────────────────────────────────────────
# Fairness checker
# ─────────────────────────────────────────────────────────────────────


class FairnessCheckerTests(unittest.TestCase):
    def _record(self, **overrides) -> AuditRecord:
        defaults: dict = dict(
            decision_id=uuid4(),
            application_id="app_1",
            decision_type="credit_assessment",
            decision_output=DecisionOutcome.ALLOW,
            confidence=0.9,
            owner="credit_risk_agent",
            mode=DecisionMode.AUTO_EXECUTE,
        )
        defaults.update(overrides)
        return AuditRecord(**defaults)

    def test_pass_when_no_baselines_provided(self):
        checker = FairnessChecker()
        result = checker.check(self._record(applicant_segment="prime"))
        self.assertEqual(result.status, CheckStatus.PASS)

    def test_pass_when_segment_within_threshold(self):
        checker = FairnessChecker(
            baseline_rates={"__overall__": 0.70, "prime": 0.78}
        )
        result = checker.check(self._record(applicant_segment="prime"))
        self.assertEqual(result.status, CheckStatus.PASS)

    def test_warn_when_segment_deviates_beyond_threshold(self):
        checker = FairnessChecker(
            baseline_rates={"__overall__": 0.70, "subprime": 0.40}
        )
        record = self._record(applicant_segment="subprime")
        result = checker.check(record)
        self.assertEqual(result.status, CheckStatus.WARN)
        self.assertTrue(record.disparate_impact_flag)
        self.assertEqual(len(record.fairness_flags), 1)


# ─────────────────────────────────────────────────────────────────────
# Engine — fan-out + aggregation
# ─────────────────────────────────────────────────────────────────────


class AuditEngineTests(unittest.TestCase):
    def test_engine_assembles_record_from_trace(self):
        engine = AuditEngine()
        trace = _trace()
        record = _run(
            engine.evaluate(
                trace,
                regulation_tags=["FCRA", "ECOA"],
                consent_status=ConsentStatus.OBTAINED,
                protected_attrs_excluded=["race", "sex"],
            )
        )
        self.assertEqual(record.application_id, trace.application_id)
        self.assertEqual(record.decision_type, trace.decision_id)
        self.assertEqual(record.decision_output, trace.outcome)
        self.assertEqual(record.confidence, trace.confidence)
        self.assertEqual(record.owner, trace.persona)
        self.assertEqual(record.mode, trace.mode)
        self.assertEqual(len(record.policy_applied), 1)
        self.assertEqual(record.policy_applied[0].policy_id, "policy:credit_assessment:v1")
        self.assertEqual(record.overall_status, CheckStatus.PASS)

    def test_engine_aggregates_worst_status(self):
        engine = AuditEngine()
        trace = _trace()
        # Missing FCRA tag → compliance WARN. No PII permissions → fine
        # since no PII fields touched. Ethics PASS.
        record = _run(
            engine.evaluate(
                trace,
                regulation_tags=["FCRA"],
                protected_attrs_excluded=["race"],
            )
        )
        self.assertEqual(record.compliance_status, CheckStatus.WARN)
        self.assertEqual(record.overall_status, CheckStatus.WARN)

    def test_engine_fails_overall_on_consent_missing(self):
        engine = AuditEngine()
        record = _run(
            engine.evaluate(
                _trace(),
                regulation_tags=["FCRA", "ECOA"],
                consent_status=ConsentStatus.MISSING,
                protected_attrs_excluded=["race"],
            )
        )
        self.assertEqual(record.compliance_status, CheckStatus.FAIL)
        self.assertEqual(record.overall_status, CheckStatus.FAIL)

    def test_engine_marks_human_reviewed_from_trace(self):
        from core.trace import HumanReview

        engine = AuditEngine()
        trace = _trace()
        trace = trace.model_copy(
            update={
                "human_review": HumanReview(
                    reviewer_id="u1",
                    reviewer_role="underwriter",
                    original_ai_decision=DecisionOutcome.ALLOW,
                    final_outcome=DecisionOutcome.ALLOW,
                )
            }
        )
        record = _run(
            engine.evaluate(
                trace,
                regulation_tags=["FCRA", "ECOA"],
            )
        )
        self.assertTrue(record.human_reviewed)


# ─────────────────────────────────────────────────────────────────────
# Store invariants
# ─────────────────────────────────────────────────────────────────────


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.store = InMemoryAuditStore()
        self.engine = AuditEngine()

    def _build(self, *, application_id: str = "app_1") -> AuditRecord:
        trace = _trace()
        trace = trace.model_copy(update={"application_id": application_id})
        return _run(
            self.engine.evaluate(
                trace,
                regulation_tags=["FCRA", "ECOA"],
                protected_attrs_excluded=["race"],
            )
        )

    def test_write_then_get(self):
        record = self._build()
        audit_id = _run(self.store.write(record))
        self.assertEqual(audit_id, record.audit_id)
        roundtrip = _run(self.store.get(audit_id))
        self.assertIsNotNone(roundtrip)
        self.assertEqual(roundtrip.audit_id, record.audit_id)

    def test_duplicate_audit_id_rejected(self):
        record = self._build()
        _run(self.store.write(record))
        with self.assertRaises(ValueError):
            _run(self.store.write(record))

    def test_list_for_application_segments_correctly(self):
        a = self._build(application_id="app_a")
        b = self._build(application_id="app_b")
        _run(self.store.write(a))
        _run(self.store.write(b))
        rows_a = _run(self.store.list_for_application("app_a"))
        self.assertEqual(len(rows_a), 1)
        self.assertEqual(rows_a[0].application_id, "app_a")

    def test_list_flags_returns_only_warn_or_fail(self):
        passing = self._build()
        # Manually mutate to force a flag — engine output of a clean
        # input is PASS.
        warn = passing.model_copy(
            update={"audit_id": uuid4(), "overall_status": CheckStatus.WARN}
        )
        _run(self.store.write(passing))
        _run(self.store.write(warn))
        flags = _run(self.store.list_flags())
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0].overall_status, CheckStatus.WARN)

    def test_log_access_appends(self):
        record = self._build()
        _run(self.store.write(record))
        _run(
            self.store.log_access(
                record.audit_id,
                AccessRecord(user_id="auditor_1", role="auditor", action="read"),
            )
        )
        log = _run(self.store.access_log(record.audit_id))
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0].user_id, "auditor_1")

    def test_log_access_unknown_audit_id_raises(self):
        with self.assertRaises(KeyError):
            _run(
                self.store.log_access(
                    uuid4(),
                    AccessRecord(user_id="u", role="r", action="read"),
                )
            )


if __name__ == "__main__":
    unittest.main()

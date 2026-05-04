"""Audit reports — six generators against synthetic AuditRecord sets.

  python -m unittest tests.core.audit.test_reports
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

from core.audit import (  # noqa: E402
    AuditRecord,
    CheckStatus,
    ConsentStatus,
    DataClassification,
    EncryptionStatus,
    FairnessFlag,
    PolicyApplied,
)
from core.audit.reports import (  # noqa: E402
    generate_ai_trail_report,
    generate_bias_report,
    generate_fair_lending_report,
    generate_hmda_report,
    generate_overrides_report,
    generate_security_report,
)
from core.normalizer.models import DecisionMode, DecisionOutcome  # noqa: E402


def _record(
    *,
    decision_type: str = "credit_assessment",
    application_id: str = "app_1",
    outcome: DecisionOutcome = DecisionOutcome.ALLOW,
    confidence: float = 0.8,
    overall: CheckStatus = CheckStatus.PASS,
    compliance: CheckStatus = CheckStatus.PASS,
    security: CheckStatus = CheckStatus.PASS,
    ethics: CheckStatus = CheckStatus.PASS,
    fairness: CheckStatus = CheckStatus.PASS,
    bias_score: float | None = None,
    segment: str | None = None,
    pii_fields: list[str] | None = None,
    permissions: list[str] | None = None,
    classification: DataClassification = DataClassification.CONFIDENTIAL,
    anomaly: bool = False,
    fairness_flags: list[FairnessFlag] | None = None,
    disparate: bool = False,
    human_reviewed: bool = False,
    timestamp: datetime | None = None,
    regulation_tags: list[str] | None = None,
    policy_id: str = "policy:credit_assessment:v1",
) -> AuditRecord:
    return AuditRecord(
        decision_id=uuid4(),
        application_id=application_id,
        decision_type=decision_type,
        timestamp=timestamp or datetime.utcnow(),
        decision_output=outcome,
        confidence=confidence,
        owner="test_owner",
        mode=DecisionMode.AUTO_EXECUTE,
        regulation_tags=regulation_tags or ["FCRA", "ECOA"],
        consent_status=ConsentStatus.OBTAINED,
        compliance_status=compliance,
        accessed_by=[],
        permissions_used=permissions or [],
        data_classification=classification,
        pii_fields_accessed=pii_fields or [],
        encryption_status=EncryptionStatus.BOTH,
        access_anomaly=anomaly,
        security_status=security,
        applicant_segment=segment,
        protected_attrs_used=[],
        protected_attrs_excluded=["race", "sex"],
        fairness_flags=fairness_flags or [],
        bias_score=bias_score,
        disparate_impact_flag=disparate,
        human_reviewed=human_reviewed,
        ethics_status=ethics,
        fairness_status=fairness,
        overall_status=overall,
        policy_applied=[
            PolicyApplied(policy_id=policy_id, result=outcome.value)
        ],
    )


def _window():
    now = datetime.utcnow()
    return now - timedelta(days=7), now + timedelta(days=1)


class HMDAReportTests(unittest.TestCase):

    def test_filters_to_hmda_decisions(self):
        records = [
            _record(decision_type="lead_scoring"),       # filtered out
            _record(decision_type="underwriting_decision"),
            _record(decision_type="closing_readiness"),
        ]
        ws, we = _window()
        report = generate_hmda_report(records, ws, we)
        self.assertEqual(report.record_count, 2)
        self.assertEqual(report.cadence, "monthly")
        self.assertIn("by_outcome", report.summary)

    def test_flags_records_with_compliance_warn(self):
        records = [
            _record(
                decision_type="underwriting_decision",
                compliance=CheckStatus.WARN,
                overall=CheckStatus.WARN,
            ),
            _record(decision_type="underwriting_decision"),
        ]
        ws, we = _window()
        report = generate_hmda_report(records, ws, we)
        self.assertEqual(len(report.flags), 1)


class FairLendingReportTests(unittest.TestCase):

    def test_segment_approval_rates_aggregate(self):
        records = (
            [_record(decision_type="underwriting_decision",
                     segment="prime", outcome=DecisionOutcome.ALLOW)] * 8
            + [_record(decision_type="underwriting_decision",
                       segment="prime", outcome=DecisionOutcome.BLOCK)] * 2
            + [_record(decision_type="underwriting_decision",
                       segment="subprime", outcome=DecisionOutcome.ALLOW)] * 3
            + [_record(decision_type="underwriting_decision",
                       segment="subprime", outcome=DecisionOutcome.BLOCK)] * 7
        )
        ws, we = _window()
        report = generate_fair_lending_report(records, ws, we)
        self.assertEqual(report.cadence, "quarterly")
        rates = {r["applicant_segment"]: r["approval_rate"] for r in report.rows}
        self.assertAlmostEqual(rates["prime"], 0.8, places=2)
        self.assertAlmostEqual(rates["subprime"], 0.3, places=2)

    def test_four_fifths_rule_flags_disparate_impact(self):
        # prime: 80% approval, subprime: 30% — ratio 0.375 < 0.80.
        records = (
            [_record(decision_type="underwriting_decision",
                     segment="prime", outcome=DecisionOutcome.ALLOW)] * 8
            + [_record(decision_type="underwriting_decision",
                       segment="prime", outcome=DecisionOutcome.BLOCK)] * 2
            + [_record(decision_type="underwriting_decision",
                       segment="subprime", outcome=DecisionOutcome.ALLOW)] * 3
            + [_record(decision_type="underwriting_decision",
                       segment="subprime", outcome=DecisionOutcome.BLOCK)] * 7
        )
        ws, we = _window()
        report = generate_fair_lending_report(records, ws, we)
        flagged_segments = {f["segment"] for f in report.flags}
        self.assertIn("subprime", flagged_segments)


class AITrailReportTests(unittest.TestCase):

    def test_per_decision_listing(self):
        records = [_record() for _ in range(5)]
        ws, we = _window()
        report = generate_ai_trail_report(records, ws, we)
        self.assertEqual(report.record_count, 5)
        self.assertEqual(len(report.rows), 5)
        self.assertEqual(report.summary["by_overall_status"], {"pass": 5})

    def test_human_reviewed_count_in_summary(self):
        records = [
            _record(human_reviewed=True),
            _record(human_reviewed=True),
            _record(human_reviewed=False),
        ]
        ws, we = _window()
        report = generate_ai_trail_report(records, ws, we)
        self.assertEqual(report.summary["human_reviewed_count"], 2)


class SecurityReportTests(unittest.TestCase):

    def test_pii_and_anomaly_aggregation(self):
        records = [
            _record(pii_fields=["ssn", "dob"], permissions=["credit_pull"]),
            _record(pii_fields=["ssn"], anomaly=True,
                    security=CheckStatus.FAIL, overall=CheckStatus.FAIL),
        ]
        ws, we = _window()
        report = generate_security_report(records, ws, we)
        self.assertEqual(report.summary["pii_field_counts"]["ssn"], 2)
        self.assertEqual(report.summary["anomaly_count"], 1)
        # Both flags fire on the second record (anomaly + security fail).
        self.assertGreaterEqual(len(report.flags), 1)


class BiasReportTests(unittest.TestCase):

    def test_score_aggregation(self):
        records = [
            _record(bias_score=0.10, segment="prime"),
            _record(bias_score=0.20, segment="prime"),
            _record(bias_score=0.35, segment="subprime",
                    ethics=CheckStatus.FAIL, overall=CheckStatus.FAIL),
        ]
        ws, we = _window()
        report = generate_bias_report(records, ws, we)
        self.assertEqual(report.summary["score_count"], 3)
        self.assertEqual(report.summary["above_action"], 1)
        self.assertEqual(report.summary["above_monitoring"], 2)
        self.assertEqual(len(report.flags), 1)
        self.assertEqual(report.flags[0]["bias_score"], 0.35)

    def test_fairness_flag_breakdown_by_segment(self):
        records = [
            _record(
                segment="subprime",
                fairness_flags=[
                    FairnessFlag(
                        attribute="subprime",
                        flag_type="segment_deviation",
                        description="x",
                    )
                ],
                disparate=True,
            ),
        ]
        ws, we = _window()
        report = generate_bias_report(records, ws, we)
        self.assertEqual(report.summary["disparate_impact_count"], 1)
        self.assertEqual(
            report.summary["by_segment"]["subprime"]["segment_deviation"], 1
        )


class OverridesReportTests(unittest.TestCase):

    def test_review_rate_and_per_decision_count(self):
        records = [
            _record(decision_type="underwriting_decision", human_reviewed=True),
            _record(decision_type="closing_readiness", human_reviewed=True),
            _record(decision_type="credit_assessment", human_reviewed=False),
        ]
        ws, we = _window()
        report = generate_overrides_report(records, ws, we)
        self.assertEqual(report.summary["reviewed_count"], 2)
        self.assertAlmostEqual(report.summary["review_rate"], 2 / 3, places=3)
        self.assertEqual(
            report.summary["by_decision_type"]["underwriting_decision"], 1
        )


class WindowFilterTests(unittest.TestCase):

    def test_records_outside_window_are_excluded(self):
        old = _record(timestamp=datetime.utcnow() - timedelta(days=30))
        new = _record(timestamp=datetime.utcnow())
        ws = datetime.utcnow() - timedelta(days=7)
        we = datetime.utcnow() + timedelta(days=1)
        report = generate_ai_trail_report([old, new], ws, we)
        self.assertEqual(report.record_count, 1)


if __name__ == "__main__":
    unittest.main()

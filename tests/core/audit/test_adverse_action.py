"""Adverse action notice generator tests.

  python -m unittest tests.core.audit.test_adverse_action
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
    ActionTaken,
    AdverseActionReason,
    AuditRecord,
    CheckStatus,
    ConsentStatus,
    DataClassification,
    EncryptionStatus,
    PolicyApplied,
    generate_notice,
    is_adverse_action,
)
from core.normalizer.models import DecisionMode, DecisionOutcome, RiskLevel  # noqa: E402
from core.trace import DecisionTrace, WorkJournalEntry  # noqa: E402


def _record(
    *,
    decision_type: str = "credit_assessment",
    outcome: DecisionOutcome = DecisionOutcome.BLOCK,
    overall: CheckStatus = CheckStatus.PASS,
    compliance: CheckStatus = CheckStatus.PASS,
    security: CheckStatus = CheckStatus.PASS,
    ethics: CheckStatus = CheckStatus.PASS,
    fairness: CheckStatus = CheckStatus.PASS,
    data_sources: list[str] | None = None,
) -> AuditRecord:
    return AuditRecord(
        decision_id=uuid4(),
        application_id="app_aa_test",
        decision_type=decision_type,
        decision_output=outcome,
        confidence=0.85,
        owner="test_owner",
        mode=DecisionMode.AUTO_EXECUTE,
        regulation_tags=["FCRA", "ECOA"],
        consent_status=ConsentStatus.OBTAINED,
        compliance_status=compliance,
        accessed_by=[],
        permissions_used=[],
        data_classification=DataClassification.CONFIDENTIAL,
        pii_fields_accessed=[],
        encryption_status=EncryptionStatus.BOTH,
        access_anomaly=False,
        security_status=security,
        applicant_segment=None,
        protected_attrs_used=[],
        protected_attrs_excluded=["race", "sex"],
        fairness_flags=[],
        bias_score=None,
        disparate_impact_flag=False,
        human_reviewed=False,
        ethics_status=ethics,
        fairness_status=fairness,
        overall_status=overall,
        data_sources_used=data_sources or ["credit_bureau"],
        policy_applied=[],
    )


def _trace(
    *,
    outcome: DecisionOutcome = DecisionOutcome.BLOCK,
    policy_reasons: list[str] | None = None,
    decision_id: str = "credit_assessment",
) -> DecisionTrace:
    return DecisionTrace(
        decision_id=decision_id,
        application_id="app_aa_test",
        agent_id="test_agent",
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
        confidence=0.85,
        policy_reasons=policy_reasons or [],
    )


# ─────────────────────────────────────────────────────────────────────
# is_adverse_action
# ─────────────────────────────────────────────────────────────────────


class IsAdverseActionTests(unittest.TestCase):

    def test_block_outcome_is_adverse(self):
        self.assertTrue(is_adverse_action(_record(outcome=DecisionOutcome.BLOCK)))

    def test_allow_outcome_is_not_adverse(self):
        self.assertFalse(is_adverse_action(_record(outcome=DecisionOutcome.ALLOW)))

    def test_recommend_outcome_is_not_adverse(self):
        self.assertFalse(
            is_adverse_action(_record(outcome=DecisionOutcome.RECOMMEND))
        )

    def test_escalate_on_underwriting_is_adverse(self):
        self.assertTrue(is_adverse_action(_record(
            decision_type="underwriting_decision",
            outcome=DecisionOutcome.ESCALATE,
        )))

    def test_escalate_on_credit_assessment_is_not_adverse(self):
        # Mid-pipeline escalate is a routing signal, not an action.
        self.assertFalse(is_adverse_action(_record(
            decision_type="credit_assessment",
            outcome=DecisionOutcome.ESCALATE,
        )))

    def test_compliance_fail_is_adverse(self):
        self.assertTrue(is_adverse_action(_record(
            decision_type="compliance_check",
            outcome=DecisionOutcome.RECOMMEND,
            overall=CheckStatus.FAIL,
            compliance=CheckStatus.FAIL,
        )))

    def test_fraud_fail_is_adverse(self):
        self.assertTrue(is_adverse_action(_record(
            decision_type="fraud_screening",
            outcome=DecisionOutcome.RECOMMEND,
            overall=CheckStatus.FAIL,
            compliance=CheckStatus.FAIL,
        )))


# ─────────────────────────────────────────────────────────────────────
# generate_notice
# ─────────────────────────────────────────────────────────────────────


class GenerateNoticeTests(unittest.TestCase):

    def test_block_decision_classifies_as_declined(self):
        record = _record(outcome=DecisionOutcome.BLOCK)
        notice = generate_notice(
            record,
            _trace(policy_reasons=["dti exceeds threshold"]),
        )
        self.assertEqual(notice.action, ActionTaken.DECLINED)
        self.assertEqual(notice.audit_id, str(record.audit_id))
        self.assertEqual(notice.application_id, "app_aa_test")

    def test_escalate_classifies_as_pending(self):
        record = _record(
            decision_type="underwriting_decision",
            outcome=DecisionOutcome.ESCALATE,
        )
        notice = generate_notice(record, _trace(outcome=DecisionOutcome.ESCALATE))
        self.assertEqual(notice.action, ActionTaken.PENDING)

    def test_dti_reason_mapped_from_policy_reasons(self):
        record = _record(decision_type="dti_calculation")
        notice = generate_notice(
            record,
            _trace(policy_reasons=["dti exceeds 0.43 threshold"]),
        )
        self.assertIn(AdverseActionReason.EXCESSIVE_OBLIGATIONS, notice.reasons)

    def test_ltv_reason_mapped_from_policy_reasons(self):
        record = _record(decision_type="ltv_assessment")
        notice = generate_notice(
            record,
            _trace(policy_reasons=["ltv exceeds 0.95 max"]),
        )
        self.assertIn(
            AdverseActionReason.INSUFFICIENT_COLLATERAL_VALUE, notice.reasons
        )

    def test_fraud_reason_mapped_from_policy_reasons(self):
        record = _record(decision_type="fraud_screening")
        notice = generate_notice(
            record,
            _trace(policy_reasons=["fraud_block_stops_pipeline"]),
        )
        self.assertIn(AdverseActionReason.SUSPECTED_FRAUD, notice.reasons)

    def test_compliance_fail_adds_regulatory_reason(self):
        record = _record(
            decision_type="compliance_check",
            outcome=DecisionOutcome.BLOCK,
            overall=CheckStatus.FAIL,
            compliance=CheckStatus.FAIL,
        )
        notice = generate_notice(record, _trace())
        self.assertIn(
            AdverseActionReason.REGULATORY_RESTRICTION, notice.reasons
        )

    def test_credit_bureau_in_sources_sets_fcra_required(self):
        record = _record(data_sources=["credit_bureau", "payroll_provider"])
        notice = generate_notice(record, _trace())
        self.assertTrue(notice.fcra_required)
        self.assertEqual(notice.bureau_used, "credit_bureau")

    def test_no_credit_bureau_means_no_fcra(self):
        record = _record(data_sources=["application_form"])
        notice = generate_notice(record, _trace())
        self.assertFalse(notice.fcra_required)
        self.assertIsNone(notice.bureau_used)

    def test_fallback_reason_when_no_signal(self):
        # No policy_reasons + no failed checks → use decision-type default.
        record = _record(decision_type="credit_assessment")
        notice = generate_notice(record, _trace())
        self.assertIn(AdverseActionReason.POOR_CREDIT_HISTORY, notice.reasons)

    def test_notice_due_30_days_from_action(self):
        record = _record()
        notice = generate_notice(record, _trace())
        self.assertEqual(
            notice.notice_due_by - notice.action_date,
            timedelta(days=30),
        )

    def test_applicant_name_pulled_when_provided(self):
        record = _record()
        notice = generate_notice(
            record,
            _trace(),
            applicant_value={
                "applicant_id": "cust_test",
                "first_name": "Alex",
                "last_name": "Patel",
            },
        )
        self.assertEqual(notice.applicant_name, "Alex Patel")
        self.assertEqual(notice.applicant_id, "cust_test")

    def test_ecoa_statement_present(self):
        record = _record()
        notice = generate_notice(record, _trace())
        self.assertIn("Equal Credit Opportunity Act", notice.ecoa_statement)


if __name__ == "__main__":
    unittest.main()

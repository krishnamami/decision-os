"""Persona _compute_offline happy-path tests — 12 personas.

Each persona is exercised with a "fully populated" ContextBundle so it
can find the entities it reads. Assertions cover:
  - reason() returns a valid AgentReasoning.
  - confidence is in [0, 1].
  - journal fields are non-empty.
  - output_payload contains the canonical keys boundary clauses
    reference (verified_income, credit_band, fraud_score, dti_ratio,
    ltv_ratio, etc.).
  - proposed_outcome is one of the expected values for the happy path.

  python -m unittest tests.domains.lending.personas.test_personas_offline
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[4]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.context_store import ContextBundle  # noqa: E402
from core.normalizer.models import DecisionOutcome  # noqa: E402
from domains.lending.personas import LENDING_PERSONA_CLASSES  # noqa: E402


# ─────────────────────────────────────────────────────────────────────
# Bundle fixture — happy path: all entities present, all signals clean
# ─────────────────────────────────────────────────────────────────────


def _bundle(decision_id: str, **overrides) -> ContextBundle:
    """Construct a ContextBundle populated with every entity type a
    persona might want to read. Each persona pulls what it needs via
    bundle.objects[<type>] and bundle.upstream_outputs."""

    objects = {
        "Applicant": {
            "cust_test": {
                "applicant_id":   "cust_test",
                "kyc_status":     "verified",
                "channel":        "digital",
                "lead_source":    "test_form",
                "session_behavior": {"pages_viewed": 8},
                "prior_inquiries": 0,
                "ambiguous_identity": False,
                "identity_match_confidence": 0.97,
            },
        },
        "Application": {
            "app_test": {
                "application_id": "app_test",
                "applicant_id":   "cust_test",
                "loan_purpose":   "purchase",
                "requested_amount": 400000,
                "property_state": "CA",
                "submitted_at":   datetime(2026, 4, 1).isoformat(),
                "status":         "intake",
            },
        },
        "Property": {
            "property_test": {
                "property_id":    "property_test",
                "application_id": "app_test",
                "appraised_value": 500000,
                "purchase_price": 480000,
                "appraisal_disputed": False,
            },
        },
        "Loan": {
            "loan_test": {
                "loan_id":        "loan_test",
                "application_id": "app_test",
                "loan_type":      "conforming",
                "principal_amount": 400000,
                "term_months":    360,
                "lock_period":    30,
                "interest_rate":  0.0625,
            },
        },
        "CreditProfile": {
            "credit_test": {
                "credit_profile_id": "credit_test",
                "applicant_id":     "cust_test",
                "bureau":           "experian",
                "credit_score":     740,
                "credit_band":      "prime",
                "open_tradelines":  6,
                "derogatory_marks": 0,
                "credit_utilization": 0.18,
                "thin_file":        False,
                "active_bankruptcy": False,
                "foreclosure_last_36_months": False,
                "no_derogatory_last_24_months": True,
                "pulled_at":        datetime(2026, 4, 1).isoformat(),
            },
        },
        "IncomeProfile": {
            "income_test": {
                "income_profile_id": "income_test",
                "applicant_id":     "cust_test",
                "application_id":   "app_test",
                "stated_income":    120000,
                "stated_employer":  "BigCo",
                "verified_income":  120000,
                "employment_type":  "salaried",
                "payroll_verified": True,
                "income_confidence_score": 0.95,
                "income_discrepancy_pct": 0.0,
                "multiple_income_sources": False,
                "foreign_income":   False,
                "verified_at":      datetime(2026, 4, 1).isoformat(),
            },
        },
        "FraudProfile": {
            "fraud_test": {
                "fraud_profile_id": "fraud_test",
                "applicant_id":     "cust_test",
                "fraud_score":      0.05,
                "identity_match_confidence": 0.97,
                "document_authenticity_score": 1.0,
                "watchlist_match":  False,
                "synthetic_identity_flag": False,
                "generated_at":     datetime(2026, 4, 1).isoformat(),
            },
        },
        "ComplianceRecord": {
            "comp_test": {
                "compliance_record_id": "comp_test",
                "application_id":   "app_test",
                "all_hmda_fields_complete": True,
                "fair_lending_violation": False,
                "missing_required_disclosures": False,
                "state_rules_passed": True,
                "cd_timing_compliant": True,
                "regulatory_ambiguity": False,
                "mixed_jurisdiction": False,
                "title_clear":      True,
                "final_conditions_checklist": {"all_cleared": True},
                "insurance_binder": True,
            },
        },
        # employment_reconciliation needs at least one VerificationAttempt
        # in the bundle to produce a non-"missing" status. Two attempts
        # with matching employer name + window so the offline path
        # produces a clean auto_verified outcome.
        "VerificationAttempt": {
            "verify_test_twn": {
                "verification_attempt_id": "verify_test_twn",
                "applicant_id":   "cust_test",
                "application_id": "app_test",
                "source":         "twn",
                "status":         "succeeded",
                "employer_name_raw": "BIGCO INC",
                "gross_amount":   120000,
                "period_start":   "2024-04-01T00:00:00",
                "period_end":     "2026-04-01T00:00:00",
                "verified":       True,
                "received_at":    datetime(2026, 4, 1).isoformat(),
            },
            "verify_test_argyle": {
                "verification_attempt_id": "verify_test_argyle",
                "applicant_id":   "cust_test",
                "application_id": "app_test",
                "source":         "argyle",
                "status":         "succeeded",
                "employer_name_raw": "BigCo",
                "gross_amount":   120000,
                "period_start":   "2024-04-01T00:00:00",
                "period_end":     "2026-04-01T00:00:00",
                "verified":       True,
                "received_at":    datetime(2026, 4, 1).isoformat(),
            },
        },
    }
    objects.update(overrides.get("objects_override", {}))

    upstream_outputs = {
        "employment_reconciliation": {
            "decision_id": "employment_reconciliation",
            "outcome":     "allow",
            "confidence":  0.92,
            "payload": {
                "reconciliation_status": "auto_verified",
                "continuity_coverage_pct": 1.0,
                "max_gap_days": 0,
                "employer_name_match_confidence": 1.0,
                "comp_drift_pct": 0.0,
                "stated_vs_verified_drift_pct": 0.0,
                "verification_attempts_count": 2,
                "employer_records": [
                    {
                        "employer_name_canonical": "bigco",
                        "start_date": "2024-04-01",
                        "end_date": "2026-04-01",
                        "tenure_months": 24,
                        "monthly_gross_estimate": 10000,
                        "corroborating_sources": ["twn", "argyle"],
                        "corroborating_attempt_ids": ["verify_test_twn", "verify_test_argyle"],
                    },
                ],
                "manual_voe_required": False,
                "gap_letter_required": False,
                "tax_transcript_required": False,
            },
        },
        "income_verification": {
            "decision_id": "income_verification",
            "outcome":     "allow",
            "confidence":  0.95,
            "payload": {
                "verified_income": 120000,
                "income_confidence_score": 0.95,
                "employment_type": "salaried",
                "payroll_verified": True,
                "income_discrepancy_pct": 0.0,
            },
        },
        "credit_assessment": {
            "decision_id": "credit_assessment",
            "outcome":     "allow",
            "confidence":  0.95,
            "payload": {
                "credit_score": 740,
                "credit_band":  "prime",
                "active_bankruptcy": False,
                "foreclosure_last_36_months": False,
                "no_derogatory_last_24_months": True,
                "thin_file":    False,
            },
        },
        "fraud_screening": {
            "decision_id": "fraud_screening",
            "outcome":     "allow",
            "confidence":  0.95,
            "payload": {
                "fraud_score":  0.05,
                "fraud_cleared": True,
                "watchlist_match": False,
                "synthetic_identity_flag": False,
                "identity_match_confidence": 0.97,
            },
        },
        "compliance_check": {
            "decision_id": "compliance_check",
            "outcome":     "allow",
            "confidence":  0.95,
            "payload": {
                "compliance_cleared": True,
                "fair_lending_violation": False,
                "missing_required_disclosures": False,
                "all_hmda_fields_complete": True,
                "state_rules_passed": True,
            },
        },
        "dti_calculation": {
            "decision_id": "dti_calculation",
            "outcome":     "allow",
            "confidence":  0.95,
            "payload": {
                "dti_ratio":       0.30,
                "verified_income": 120000,
            },
        },
        "ltv_assessment": {
            "decision_id": "ltv_assessment",
            "outcome":     "allow",
            "confidence":  0.95,
            "payload": {
                "ltv_ratio":      0.80,
                "appraised_value": 500000,
                "loan_amount":    400000,
                "credit_band":    "prime",
            },
        },
        "product_eligibility": {
            "decision_id": "product_eligibility",
            "outcome":     "allow",
            "confidence":  0.85,
            "payload": {
                "eligible_products": ["conforming_30yr"],
                "no_eligible_products": False,
                "eligible_with_exceptions": False,
                "guideline_exceptions_required": [],
            },
        },
        "rate_pricing": {
            "decision_id": "rate_pricing",
            "outcome":     "allow",
            "confidence":  0.9,
            "payload": {
                "interest_rate": 0.0625,
                "llpa":          0.0,
                "rate_within_normal_band": True,
                "no_manual_adjustments_required": True,
                "loan_type":     "conforming",
            },
        },
        "underwriting_decision": {
            "decision_id": "underwriting_decision",
            "outcome":     "recommend",
            "confidence":  0.85,
            "payload": {
                "underwriting_outcome": "approve",
                "risk_score":   0.20,
                "all_upstream_auto_cleared": True,
                "any_upstream_hard_block": False,
                "no_exceptions_required": True,
            },
        },
    }

    return ContextBundle(
        decision_id=decision_id,
        application_id="app_test",
        snapshot_id=uuid4(),
        snapshot_at=datetime(2026, 4, 1),
        context_window_days=90,
        objects=objects,
        upstream_outputs=upstream_outputs,
        upstream_decision_ids=list(upstream_outputs.keys()),
    )


# ─────────────────────────────────────────────────────────────────────
# Per-persona happy-path expectations
# ─────────────────────────────────────────────────────────────────────


# (decision_id, expected payload key(s), expected outcome on happy path)
# Some personas can land on ALLOW or RECOMMEND depending on the
# offline rules; we accept either when the spec allows.
_HAPPY_PATH_EXPECTATIONS: dict[str, dict] = {
    "lead_scoring":          {"keys": ["intent_score"],
                              "outcomes": {DecisionOutcome.ALLOW, DecisionOutcome.RECOMMEND}},
    "employment_reconciliation": {
        "keys": ["reconciliation_status", "continuity_coverage_pct",
                 "employer_records"],
        "outcomes": {DecisionOutcome.ALLOW, DecisionOutcome.RECOMMEND,
                     DecisionOutcome.ESCALATE},
    },
    "income_verification":   {"keys": ["verified_income", "income_confidence_score"],
                              "outcomes": {DecisionOutcome.ALLOW, DecisionOutcome.RECOMMEND}},
    "credit_assessment":     {"keys": ["credit_score", "credit_band"],
                              "outcomes": {DecisionOutcome.ALLOW}},
    "fraud_screening":       {"keys": ["fraud_score"],
                              "outcomes": {DecisionOutcome.ALLOW}},
    "compliance_check":      {"keys": ["compliance_cleared"],
                              "outcomes": {DecisionOutcome.ALLOW, DecisionOutcome.RECOMMEND}},
    "dti_calculation":       {"keys": ["dti_ratio"],
                              "outcomes": {DecisionOutcome.ALLOW, DecisionOutcome.RECOMMEND}},
    "ltv_assessment":        {"keys": ["ltv_ratio"],
                              "outcomes": {DecisionOutcome.ALLOW, DecisionOutcome.RECOMMEND}},
    "product_eligibility":   {"keys": ["eligible_products"],
                              "outcomes": {DecisionOutcome.ALLOW, DecisionOutcome.RECOMMEND}},
    "rate_pricing":          {"keys": ["interest_rate"],
                              "outcomes": {DecisionOutcome.ALLOW, DecisionOutcome.RECOMMEND}},
    "underwriting_decision": {"keys": ["risk_score"],
                              "outcomes": {DecisionOutcome.ALLOW, DecisionOutcome.RECOMMEND, DecisionOutcome.ESCALATE}},
    "approval_routing":      {"keys": ["routing_target"],
                              "outcomes": {DecisionOutcome.ALLOW, DecisionOutcome.RECOMMEND}},
    "closing_readiness":     {"keys": ["clear_to_close"],
                              "outcomes": {DecisionOutcome.ALLOW, DecisionOutcome.RECOMMEND}},
}


class PersonaOfflineHappyPathTests(unittest.IsolatedAsyncioTestCase):
    """One test method per persona — easier debugging when one fails."""

    async def _exercise(self, decision_id: str):
        cls = LENDING_PERSONA_CLASSES[decision_id]
        agent = cls()  # offline path by default
        bundle = _bundle(decision_id)
        result = await agent.reason(bundle, policy=None)

        self.assertIsNotNone(result)
        # confidence in [0, 1]
        self.assertGreaterEqual(result.confidence, 0.0)
        self.assertLessEqual(result.confidence, 1.0)
        # journal non-empty
        self.assertTrue(result.journal.hypothesis_tested.strip())
        self.assertTrue(result.journal.conclusion.strip())
        self.assertTrue(result.journal.confidence_basis.strip())
        self.assertTrue(result.journal.human_readable_summary.strip())
        # signals non-empty (critic flags zero-signal traces)
        self.assertGreater(
            len(result.journal.signals_evaluated), 0,
            f"{decision_id}: signals_evaluated must be non-empty",
        )
        # expected outcome + payload keys
        exp = _HAPPY_PATH_EXPECTATIONS[decision_id]
        self.assertIn(
            result.proposed_outcome, exp["outcomes"],
            f"{decision_id}: outcome {result.proposed_outcome} not in {exp['outcomes']}",
        )
        for key in exp["keys"]:
            self.assertIn(
                key, result.output_payload,
                f"{decision_id}: missing payload key {key!r}",
            )

    async def test_lead_scoring(self):           await self._exercise("lead_scoring")
    async def test_employment_reconciliation(self): await self._exercise("employment_reconciliation")
    async def test_income_verification(self):    await self._exercise("income_verification")
    async def test_credit_assessment(self):      await self._exercise("credit_assessment")
    async def test_fraud_screening(self):        await self._exercise("fraud_screening")
    async def test_compliance_check(self):       await self._exercise("compliance_check")
    async def test_dti_calculation(self):        await self._exercise("dti_calculation")
    async def test_ltv_assessment(self):         await self._exercise("ltv_assessment")
    async def test_product_eligibility(self):    await self._exercise("product_eligibility")
    async def test_rate_pricing(self):           await self._exercise("rate_pricing")
    async def test_underwriting_decision(self):  await self._exercise("underwriting_decision")
    async def test_approval_routing(self):       await self._exercise("approval_routing")
    async def test_closing_readiness(self):      await self._exercise("closing_readiness")


class PersonaRegistryTests(unittest.TestCase):

    def test_registry_has_15_personas(self):
        # 12 lending decisions + employment_reconciliation (Session 11)
        # + asset_verification (Session 16) + title_assessment (Session 18).
        self.assertEqual(len(LENDING_PERSONA_CLASSES), 15)

    def test_each_persona_class_has_decision_id_match(self):
        for decision_id, cls in LENDING_PERSONA_CLASSES.items():
            instance = cls()
            self.assertEqual(instance.decision_id, decision_id)


if __name__ == "__main__":
    unittest.main()

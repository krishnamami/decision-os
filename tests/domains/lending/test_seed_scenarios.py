"""Seed scenarios as canonical regressions.

7 scenarios run on FRESH platforms each (no cross-contamination):

  happy_path        — 12 decisions complete, no halt
  fraud_block       — fraud_screening BLOCKs, halt_reason=
                      fraud_block_stops_pipeline, dependents skipped
  contamination     — DTI BLOCKs via contamination_guard
                      (income_verification confidence=0.50 < 0.75)
  compliance_block  — closing_readiness BLOCKs via
                      compliance_block_stops_closing
  fha               — multi-agency policy_chain on ltv_assessment:
                      [lender_overlay::ltv_assessment::v1,
                       fha::ltv_assessment::v1]
  jumbo             — single-agency chain (no agency conforming
                      guideline applies to jumbo)
  va                — chain helper returns [lender_overlay, va] but
                      no VA overlay seeded → single-entry chain

Replaces smoke_replayer / smoke_workbench / smoke_fha_scenario for CI
purposes. Smokes remain useful as `python ... .py` walk-throughs.

  python -m unittest tests.domains.lending.test_seed_scenarios
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from api.deps import build_default_platform  # noqa: E402
from core.policy_engine import (  # noqa: E402
    seed_fha_demo_policies,
    seed_policies_from_yaml,
)
from domains.lending.personas import register_with_platform  # noqa: E402
from domains.lending.seed_events.runner import (  # noqa: E402
    APPLICATION_IDS,
    run_scenario,
)


async def _fresh_platform_and_run(scenario: str):
    """Build a fresh platform, seed both policy seeders, register
    personas, run the scenario. Returns (platform, run_result)."""
    p = build_default_platform()
    register_with_platform(p)
    await seed_policies_from_yaml(p.spec, p.policy_store)
    await seed_fha_demo_policies(p.policy_store)
    res = await run_scenario(p, scenario)
    return p, res


class HappyPathTests(unittest.IsolatedAsyncioTestCase):

    async def test_completes_all_13_no_halt(self):
        # 13 = 12 lending + employment_reconciliation (shadow).
        p, res = await _fresh_platform_and_run("happy_path")
        self.assertFalse(res.execution.halted)
        self.assertEqual(len(res.execution.completed_decisions), 13)
        self.assertEqual(len(res.execution.skipped_decisions), 0)


class FraudBlockTests(unittest.IsolatedAsyncioTestCase):

    async def test_pipeline_halts_on_fraud_block(self):
        p, res = await _fresh_platform_and_run("fraud_block")
        self.assertTrue(res.execution.halted)
        self.assertEqual(res.execution.halt_reason, "fraud_block_stops_pipeline")

    async def test_fraud_screening_outcome_is_block(self):
        p, res = await _fresh_platform_and_run("fraud_block")
        traces = list(p.trace_writer._traces.values())
        fraud = next(
            (t for t in traces if t.decision_id == "fraud_screening"), None
        )
        self.assertIsNotNone(fraud)
        self.assertEqual(fraud.outcome.value, "block")

    async def test_dependents_skipped_with_fraud_block_reason(self):
        # All 7 downstream decisions should be skipped after the
        # fraud_screening block fires.
        p, res = await _fresh_platform_and_run("fraud_block")
        skipped = set(res.execution.skipped_decisions)
        for did in (
            "dti_calculation", "ltv_assessment", "product_eligibility",
            "rate_pricing", "underwriting_decision", "approval_routing",
            "closing_readiness",
        ):
            self.assertIn(did, skipped, f"{did} should be skipped")


class ContaminationTests(unittest.IsolatedAsyncioTestCase):

    async def test_dti_blocks_via_contamination_guard(self):
        p, res = await _fresh_platform_and_run("contamination")
        traces = list(p.trace_writer._traces.values())
        dti = next(
            (t for t in traces if t.decision_id == "dti_calculation"), None
        )
        self.assertIsNotNone(dti)
        self.assertEqual(dti.outcome.value, "block")
        self.assertTrue(dti.contamination)
        self.assertTrue(any(
            "contamination_guard" in r for r in (dti.policy_reasons or [])
        ))


class ComplianceBlockTests(unittest.IsolatedAsyncioTestCase):

    async def test_compliance_check_blocks(self):
        p, res = await _fresh_platform_and_run("compliance_block")
        traces = list(p.trace_writer._traces.values())
        comp = next(
            (t for t in traces if t.decision_id == "compliance_check"), None
        )
        self.assertIsNotNone(comp)
        self.assertEqual(comp.outcome.value, "block")

    async def test_closing_readiness_blocks_via_specific_rule(self):
        # closing_readiness should produce policy_reasons containing
        # the specific compliance_block_stops_closing rule.
        p, res = await _fresh_platform_and_run("compliance_block")
        traces = list(p.trace_writer._traces.values())
        closing = next(
            (t for t in traces if t.decision_id == "closing_readiness"), None
        )
        self.assertIsNotNone(closing)
        self.assertEqual(closing.outcome.value, "block")
        self.assertTrue(any(
            "compliance_block_stops_closing" in r
            for r in (closing.policy_reasons or [])
        ))


class FhaScenarioTests(unittest.IsolatedAsyncioTestCase):

    async def test_completes_all_13(self):
        p, res = await _fresh_platform_and_run("fha")
        self.assertFalse(res.execution.halted)
        self.assertEqual(len(res.execution.completed_decisions), 13)

    async def test_ltv_chain_is_two_entries(self):
        # FHA loan_type → atomic_tool's agency_chain helper returns
        # ["lender_overlay", "fha"]. Both have seeded versions
        # → policy_chain has 2 entries.
        p, res = await _fresh_platform_and_run("fha")
        traces = list(p.trace_writer._traces.values())
        ltv = next(
            (t for t in traces if t.decision_id == "ltv_assessment"), None
        )
        self.assertIsNotNone(ltv)
        self.assertEqual(len(ltv.policy_chain), 2)
        self.assertIn("lender_overlay::ltv_assessment::v1", ltv.policy_chain)
        self.assertIn("fha::ltv_assessment::v1", ltv.policy_chain)
        # Overlay-first: lender_overlay is the chosen version.
        self.assertEqual(
            ltv.policy_version_id, "lender_overlay::ltv_assessment::v1"
        )


class JumboScenarioTests(unittest.IsolatedAsyncioTestCase):

    async def test_completes_all_12_single_entry_chain(self):
        # jumbo → agency_chain=["lender_overlay"] only. Single-entry chain.
        p, res = await _fresh_platform_and_run("jumbo")
        self.assertFalse(res.execution.halted)
        traces = list(p.trace_writer._traces.values())
        ltv = next(
            (t for t in traces if t.decision_id == "ltv_assessment"), None
        )
        self.assertIsNotNone(ltv)
        self.assertEqual(len(ltv.policy_chain), 1)
        self.assertEqual(
            ltv.policy_version_id, "lender_overlay::ltv_assessment::v1"
        )


class VaScenarioTests(unittest.IsolatedAsyncioTestCase):

    async def test_completes_all_12_single_entry_chain_pending_va_seed(self):
        # va → agency_chain=["lender_overlay", "va"] but no VA
        # PolicyVersion is seeded yet (real bulletins come via STREAM E2).
        # Chain stays single-entry until that lands.
        p, res = await _fresh_platform_and_run("va")
        self.assertFalse(res.execution.halted)
        traces = list(p.trace_writer._traces.values())
        ltv = next(
            (t for t in traces if t.decision_id == "ltv_assessment"), None
        )
        self.assertIsNotNone(ltv)
        self.assertEqual(len(ltv.policy_chain), 1)
        self.assertEqual(
            ltv.policy_version_id, "lender_overlay::ltv_assessment::v1"
        )


class CrossScenarioPolicyVersionTests(unittest.IsolatedAsyncioTestCase):

    async def test_every_trace_in_every_scenario_carries_stamp(self):
        # Spot-check: every trace in every scenario gets policy_version_id
        # stamped because both policy seeders run before the DAG.
        for scenario in APPLICATION_IDS:
            p, res = await _fresh_platform_and_run(scenario)
            traces = list(p.trace_writer._traces.values())
            for t in traces:
                self.assertIsNotNone(
                    t.policy_version_id,
                    f"{scenario}/{t.decision_id} missing policy_version_id",
                )


class ClaimProvenanceTests(unittest.IsolatedAsyncioTestCase):

    async def test_income_verification_stamps_claim_provenance(self):
        # happy_path seeds a verified W-2 + 2 verified claims for
        # income_verification. The trace must capture both claims
        # with full provenance (doc_id, page, verifier).
        p, res = await _fresh_platform_and_run("happy_path")
        traces = list(p.trace_writer._traces.values())
        iv = next(t for t in traces if t.decision_id == "income_verification")
        self.assertEqual(len(iv.claim_provenance), 2)
        fields = {c.field_name for c in iv.claim_provenance}
        self.assertIn("verified_income", fields)
        self.assertIn("employer", fields)
        income_claim = next(
            c for c in iv.claim_provenance if c.field_name == "verified_income"
        )
        self.assertEqual(income_claim.field_value, 124500)
        self.assertEqual(income_claim.document_id, "doc_happy_w2")
        self.assertEqual(income_claim.source_page, 1)
        self.assertEqual(income_claim.verified_by, "underwriter:bgoud")
        self.assertEqual(income_claim.status, "verified")

    async def test_decision_without_consuming_docs_has_empty_provenance(self):
        # fraud_screening's doc_type matrix entries don't include
        # happy_path's seeded W-2 doc, so the bundle has no claims.
        p, res = await _fresh_platform_and_run("happy_path")
        traces = list(p.trace_writer._traces.values())
        fs = next(t for t in traces if t.decision_id == "fraud_screening")
        self.assertEqual(fs.claim_provenance, [])

    async def test_ltv_assessment_stamps_appraisal_claim(self):
        # happy_path also seeds a verified appraisal doc + claim.
        p, res = await _fresh_platform_and_run("happy_path")
        traces = list(p.trace_writer._traces.values())
        ltv = next(t for t in traces if t.decision_id == "ltv_assessment")
        self.assertEqual(len(ltv.claim_provenance), 1)
        c = ltv.claim_provenance[0]
        self.assertEqual(c.field_name, "appraised_value")
        self.assertEqual(c.field_value, 525000)
        self.assertEqual(c.document_id, "doc_happy_appraisal")


class AuditGateTests(unittest.IsolatedAsyncioTestCase):
    """PRD §23.9 audit_record_required_before_writeback — every
    decision the atomic_tool runs must produce a corresponding
    AuditRecord in the AuditStore."""

    async def test_happy_path_writes_audit_record_per_decision(self):
        p, res = await _fresh_platform_and_run("happy_path")
        records = await p.audit_store.list_for_application(
            APPLICATION_IDS["happy_path"]
        )
        # 13 decisions → 13 audit records (12 lending + employment_reconciliation).
        self.assertEqual(len(records), 13)
        decision_types = {r.decision_type for r in records}
        for did in (
            "lead_scoring", "income_verification", "credit_assessment",
            "fraud_screening", "compliance_check", "dti_calculation",
            "ltv_assessment", "product_eligibility", "rate_pricing",
            "underwriting_decision", "approval_routing", "closing_readiness",
        ):
            self.assertIn(did, decision_types)

    async def test_audit_record_carries_decision_provenance(self):
        p, res = await _fresh_platform_and_run("happy_path")
        records = await p.audit_store.list_for_application(
            APPLICATION_IDS["happy_path"]
        )
        credit = next(r for r in records if r.decision_type == "credit_assessment")
        # Identity
        self.assertEqual(credit.application_id, APPLICATION_IDS["happy_path"])
        self.assertIsNotNone(credit.decision_id)
        # Decision block
        self.assertEqual(credit.owner, "credit_risk_agent")
        self.assertEqual(
            credit.mode.value,
            p.spec.decision_index["credit_assessment"]["mode"],
        )
        # Compliance block stamped from defaults
        self.assertIn("FCRA", credit.regulation_tags)
        self.assertIn("ECOA", credit.regulation_tags)
        self.assertIn("credit_bureau", credit.data_sources_used)
        # Aggregate status — happy path runs clean
        self.assertEqual(credit.overall_status.value, "pass")

    async def test_fraud_block_still_audits_dependents_that_executed(self):
        # Even when the pipeline halts, the decisions that DID execute
        # (lead/income/credit/fraud/compliance) must each have an
        # AuditRecord. Skipped dependents do not.
        p, res = await _fresh_platform_and_run("fraud_block")
        records = await p.audit_store.list_for_application(
            APPLICATION_IDS["fraud_block"]
        )
        completed = set(res.execution.completed_decisions)
        self.assertEqual(
            {r.decision_type for r in records},
            completed,
            "every executed decision must produce an AuditRecord",
        )

    async def test_audit_store_is_append_only(self):
        # Re-writing the same record id must raise — the in-memory
        # store enforces the §23.9 audit_records_never_deleted invariant.
        p, res = await _fresh_platform_and_run("happy_path")
        records = await p.audit_store.list_for_application(
            APPLICATION_IDS["happy_path"]
        )
        with self.assertRaises(ValueError):
            await p.audit_store.write(records[0])

    async def test_audit_record_carries_property_state_for_hmda(self):
        # HMDA report's by_state aggregation reads
        # AuditRecord.execution_result.property_state. atomic_tool
        # plumbs that from Application → audit so HMDA has data.
        p, res = await _fresh_platform_and_run("happy_path")
        records = await p.audit_store.list_for_application(
            APPLICATION_IDS["happy_path"]
        )
        # At least one of the HMDA-relevant records must carry state.
        hmda_types = {"underwriting_decision", "approval_routing", "closing_readiness"}
        with_state = [
            r for r in records
            if r.decision_type in hmda_types
            and r.execution_result.get("property_state")
        ]
        self.assertGreater(len(with_state), 0)


if __name__ == "__main__":
    unittest.main()

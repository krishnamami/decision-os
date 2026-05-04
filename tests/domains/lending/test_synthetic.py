"""Synthetic data factory + end-to-end audit integration.

  python -m unittest tests.domains.lending.test_synthetic
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
from domains.lending.synthetic import (  # noqa: E402
    SEGMENTS,
    STATES,
    build_synthetic_applicants,
    inject_into_platform,
)


class FactoryDeterminismTests(unittest.TestCase):

    def test_same_seed_produces_identical_profiles(self):
        a = build_synthetic_applicants(10, seed=7)
        b = build_synthetic_applicants(10, seed=7)
        self.assertEqual(
            [(p.applicant_id, p.credit_band, p.loan_type, p.state) for p in a],
            [(p.applicant_id, p.credit_band, p.loan_type, p.state) for p in b],
        )

    def test_different_seed_diverges(self):
        a = build_synthetic_applicants(10, seed=7)
        b = build_synthetic_applicants(10, seed=8)
        differ = sum(
            1 for x, y in zip(a, b)
            if (x.credit_band, x.loan_type, x.state)
            != (y.credit_band, y.loan_type, y.state)
        )
        self.assertGreater(differ, 0)


class FactoryDistributionTests(unittest.TestCase):

    def test_ids_are_unique_and_padded(self):
        profiles = build_synthetic_applicants(24)
        ids = [p.applicant_id for p in profiles]
        self.assertEqual(len(set(ids)), len(ids))
        # Format: cust_synth_NNN
        for pid in ids:
            self.assertTrue(pid.startswith("cust_synth_"))

    def test_segments_drawn_from_known_palette(self):
        profiles = build_synthetic_applicants(50)
        bands = {p.credit_band for p in profiles}
        valid = {s[0] for s in SEGMENTS}
        self.assertTrue(bands.issubset(valid))

    def test_states_drawn_from_known_palette(self):
        profiles = build_synthetic_applicants(50)
        seen = {p.state for p in profiles}
        self.assertTrue(seen.issubset(set(STATES)))

    def test_each_profile_has_five_documents(self):
        profiles = build_synthetic_applicants(5)
        for p in profiles:
            self.assertEqual(len(p.documents), 5)
            doc_types = {d.doc_type for d in p.documents}
            self.assertIn("w2", doc_types)
            self.assertIn("appraisal_report", doc_types)

    def test_overlay_proportions_match_rates(self):
        profiles = build_synthetic_applicants(20, fail_rate=0.10, warn_rate=0.20)
        n_fail = sum(
            1 for p in profiles
            if p.overlay.consent_missing or p.overlay.protected_attr_leak
        )
        n_warn = sum(1 for p in profiles if p.overlay.no_disclosure)
        # rounded to integers from the rates × n
        self.assertEqual(n_fail, 2)
        self.assertEqual(n_warn, 4)


class InjectAndAuditTests(unittest.IsolatedAsyncioTestCase):
    """Inject 6 synthetic applicants into a fresh platform, run the
    DAG for each, and verify the audit gate produces records that
    capture the intentional violations."""

    async def asyncSetUp(self):
        self.platform = build_default_platform()
        register_with_platform(self.platform)
        await seed_policies_from_yaml(self.platform.spec, self.platform.policy_store)
        await seed_fha_demo_policies(self.platform.policy_store)

        # Hand-rolled tiny set so the test is deterministic and fast.
        # 1 clean / 1 consent_missing / 1 protected_attr_leak.
        from domains.lending.synthetic.factory import (
            ApplicantProfile, AuditOverlay, DocumentSpec,
        )
        self.profiles = [
            ApplicantProfile(
                applicant_id="cust_T1", application_id="app_T1",
                first_name="A", last_name="One",
                age=30, age_band="25-35",
                state="CA", loan_type="conforming",
                credit_score=720, credit_band="prime",
                annual_income=120_000, requested_amount=400_000,
                appraised_value=525_000,
                documents=[DocumentSpec(
                    document_id="doc_T1_w2", doc_type="w2",
                    source_url="edms://test/w2",
                )],
            ),
            ApplicantProfile(
                applicant_id="cust_T2", application_id="app_T2",
                first_name="B", last_name="Two",
                age=40, age_band="35-50",
                state="TX", loan_type="conforming",
                credit_score=720, credit_band="prime",
                annual_income=120_000, requested_amount=400_000,
                appraised_value=525_000,
                documents=[DocumentSpec(
                    document_id="doc_T2_w2", doc_type="w2",
                    source_url="edms://test/w2",
                )],
                overlay=AuditOverlay(consent_missing=True),
            ),
            ApplicantProfile(
                applicant_id="cust_T3", application_id="app_T3",
                first_name="C", last_name="Three",
                age=50, age_band="35-50",
                state="NY", loan_type="conforming",
                credit_score=720, credit_band="prime",
                annual_income=120_000, requested_amount=400_000,
                appraised_value=525_000,
                documents=[DocumentSpec(
                    document_id="doc_T3_w2", doc_type="w2",
                    source_url="edms://test/w2",
                )],
                overlay=AuditOverlay(protected_attr_leak=True),
            ),
        ]
        self.app_ids = await inject_into_platform(self.platform, self.profiles)

        for app_id in self.app_ids:
            await self.platform.executor().run_application(
                app_id, self.platform.entity_resolver
            )

    async def test_clean_applicant_passes_audit(self):
        records = await self.platform.audit_store.list_for_application("app_T1")
        statuses = {r.overall_status.value for r in records}
        self.assertIn("pass", statuses)
        self.assertNotIn("fail", statuses)

    async def test_consent_missing_fails_compliance_on_every_decision(self):
        records = await self.platform.audit_store.list_for_application("app_T2")
        compliance_fails = [
            r for r in records if r.compliance_status.value == "fail"
        ]
        self.assertEqual(len(compliance_fails), len(records))
        for r in compliance_fails:
            self.assertEqual(r.consent_status.value, "missing")

    async def test_protected_attr_leak_fails_ethics_on_every_decision(self):
        records = await self.platform.audit_store.list_for_application("app_T3")
        ethics_fails = [r for r in records if r.ethics_status.value == "fail"]
        self.assertEqual(len(ethics_fails), len(records))
        for r in ethics_fails:
            self.assertIn("race", r.protected_attrs_used)
            self.assertNotIn("race", r.protected_attrs_excluded)


if __name__ == "__main__":
    unittest.main()

"""ui.views tests — pure-function view-model helpers + Platform-driven
view-models (list_applications, persona_workbench_view, etc.).

Boots a real Platform (in-memory) so the view-models read against
realistic state. Pure-function helpers (loan-type label, name
generator, initials, risk pill) are tested without Platform.

  python -m unittest tests.ui.test_views
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from api.deps import build_default_platform  # noqa: E402
from core.policy_engine import (  # noqa: E402
    seed_fha_demo_policies,
    seed_policies_from_yaml,
)
from domains.lending.personas import register_with_platform  # noqa: E402
from domains.lending.seed_events.runner import run_scenario  # noqa: E402
from ui.views import (  # noqa: E402
    LOAN_TYPE_LABELS,
    OUTCOME_STYLES,
    PERSONA_LABELS,
    _avatar_tone,
    _display_name,
    _friendly_name_from_id,
    _initials,
    _loan_summary,
    _loan_type_label,
    _minutes_ago,
    _risk_pill_for_confidence,
    _risk_pill_for_persona,
    application_detail,
    audit_record_detail,
    decision_detail,
    list_applications,
    list_audit_flags,
    list_audit_for_application,
    list_persona_workbenches,
    list_workbenches,
    persona_workbench_view,
    queue_view,
    workbench_view,
)


# ─────────────────────────────────────────────────────────────────────
# Pure helpers — no Platform required
# ─────────────────────────────────────────────────────────────────────


class LoanTypeLabelTests(unittest.TestCase):

    def test_known_loan_types_get_correct_casing(self):
        self.assertEqual(_loan_type_label("conforming"), "Conforming")
        self.assertEqual(_loan_type_label("jumbo"), "Jumbo")
        self.assertEqual(_loan_type_label("fha"), "FHA")
        self.assertEqual(_loan_type_label("va"), "VA")
        self.assertEqual(_loan_type_label("usda"), "USDA")
        self.assertEqual(_loan_type_label("non_qm"), "Non-QM")

    def test_unknown_type_falls_back_to_title_case(self):
        self.assertEqual(_loan_type_label("hard_money"), "Hard Money")
        self.assertEqual(_loan_type_label("bridge"), "Bridge")

    def test_none_returns_empty(self):
        self.assertEqual(_loan_type_label(None), "")
        self.assertEqual(_loan_type_label(""), "")

    def test_uppercase_input_normalizes(self):
        # User might pass FHA pre-upcased — should still resolve.
        self.assertEqual(_loan_type_label("FHA"), "FHA")
        self.assertEqual(_loan_type_label("Va"), "VA")

    def test_label_map_covers_all_canonical_loan_types(self):
        # Sanity: every value in LOAN_TYPE_LABELS is non-empty.
        for k, v in LOAN_TYPE_LABELS.items():
            self.assertTrue(v, f"empty label for {k}")


class FriendlyNameTests(unittest.TestCase):

    def test_returns_none_for_empty(self):
        self.assertIsNone(_friendly_name_from_id(""))
        self.assertIsNone(_friendly_name_from_id(None))

    def test_deterministic_across_calls(self):
        a1 = _friendly_name_from_id("cust_jumbo")
        a2 = _friendly_name_from_id("cust_jumbo")
        self.assertEqual(a1, a2)

    def test_different_ids_likely_different_names(self):
        # Not strictly guaranteed (collisions possible) but very likely
        # for short distinct inputs.
        a = _friendly_name_from_id("cust_a")
        b = _friendly_name_from_id("cust_b_different")
        # At least one should differ when the inputs do.
        self.assertNotEqual(a, b)

    def test_format_is_first_last(self):
        name = _friendly_name_from_id("anything")
        self.assertIn(" ", name)
        first, last = name.split(" ", 1)
        self.assertTrue(first[0].isupper())
        self.assertTrue(last[0].isupper())


class InitialsTests(unittest.TestCase):

    def test_initials_from_friendly_name(self):
        # _display_name produces "First Last"; initials → "FL".
        app_value = {"applicant_id": "cust_test"}
        result = _initials(app_value, "app_test")
        self.assertEqual(len(result), 2)
        self.assertTrue(result.isupper() or result == "—")

    def test_initials_em_dash_for_empty(self):
        self.assertEqual(_initials({"applicant_id": None}, ""), "—")


class DisplayNameTests(unittest.TestCase):

    def test_full_name_wins_over_applicant_id(self):
        out = _display_name({"full_name": "Real Name", "applicant_id": "cust_x"}, "app_x")
        self.assertEqual(out, "Real Name")

    def test_falls_back_to_friendly_name_from_applicant_id(self):
        out = _display_name({"applicant_id": "cust_jumbo"}, "app_jumbo")
        # Either the friendly name (deterministic) or the raw id.
        self.assertNotEqual(out, "")

    def test_falls_back_to_application_id(self):
        out = _display_name({}, "app_orphan")
        self.assertEqual(out, "app_orphan")


class AvatarToneTests(unittest.TestCase):

    def test_tone_deterministic(self):
        self.assertEqual(_avatar_tone("cust_jumbo"), _avatar_tone("cust_jumbo"))

    def test_empty_returns_slate(self):
        self.assertEqual(_avatar_tone(""), "slate")


class LoanSummaryTests(unittest.TestCase):

    def test_full_summary(self):
        out = _loan_summary(
            {"application_id": "app1"},
            {"loan_type": "fha", "term_months": 360},
        )
        self.assertIn("app1", out)
        self.assertIn("FHA 30yr", out)

    def test_dash_when_empty(self):
        out = _loan_summary({}, {})
        self.assertEqual(out, "—")

    def test_va_uppercased(self):
        out = _loan_summary(
            {"application_id": "app_va"},
            {"loan_type": "va", "term_months": 360},
        )
        self.assertIn("VA 30yr", out)


class RiskPillTests(unittest.TestCase):

    def test_confidence_pill_high(self):
        self.assertEqual(_risk_pill_for_confidence(0.95), "low")
        self.assertEqual(_risk_pill_for_confidence(0.75), "medium")
        self.assertEqual(_risk_pill_for_confidence(0.40), "high")

    def test_confidence_pill_none(self):
        self.assertEqual(_risk_pill_for_confidence(None), "medium")

    def test_persona_pill_credit_band(self):
        # Carry a stub object with output_payload attr.
        class FakeTrace:
            def __init__(self, payload):
                self.output_payload = payload
                self.confidence = 0.95

        self.assertEqual(
            _risk_pill_for_persona(
                "credit_assessment", FakeTrace({"credit_band": "prime"})
            ),
            "low",
        )
        self.assertEqual(
            _risk_pill_for_persona(
                "credit_assessment", FakeTrace({"credit_band": "near_prime"})
            ),
            "medium",
        )
        self.assertEqual(
            _risk_pill_for_persona(
                "credit_assessment", FakeTrace({"credit_band": "subprime"})
            ),
            "high",
        )

    def test_persona_pill_fraud_score(self):
        class FakeTrace:
            def __init__(self, payload):
                self.output_payload = payload
                self.confidence = 0.95

        self.assertEqual(
            _risk_pill_for_persona(
                "fraud_screening", FakeTrace({"fraud_score": 0.05})
            ),
            "low",
        )
        self.assertEqual(
            _risk_pill_for_persona(
                "fraud_screening", FakeTrace({"fraud_score": 0.6})
            ),
            "high",
        )

    def test_persona_pill_ltv(self):
        class FakeTrace:
            def __init__(self, payload):
                self.output_payload = payload
                self.confidence = 0.95

        self.assertEqual(
            _risk_pill_for_persona(
                "ltv_assessment", FakeTrace({"ltv_ratio": 0.78})
            ),
            "low",
        )
        self.assertEqual(
            _risk_pill_for_persona(
                "ltv_assessment", FakeTrace({"ltv": 0.96})
            ),
            "high",
        )


class MinutesAgoTests(unittest.TestCase):

    def test_none_returns_none(self):
        self.assertIsNone(_minutes_ago(None))

    def test_recent_returns_small_int(self):
        from datetime import datetime, timedelta
        recent = datetime.utcnow() - timedelta(minutes=5)
        result = _minutes_ago(recent)
        self.assertIsNotNone(result)
        self.assertGreaterEqual(result, 4)
        self.assertLessEqual(result, 6)


# ─────────────────────────────────────────────────────────────────────
# Platform-driven view-models — boot a fresh Platform per class so the
# view-models see realistic state.
# ─────────────────────────────────────────────────────────────────────


class _PlatformFixture:
    """Sync helper around an async Platform setup."""

    @classmethod
    def setup(cls, scenarios=("happy_path",)):
        async def _do():
            p = build_default_platform()
            register_with_platform(p)
            await seed_policies_from_yaml(p.spec, p.policy_store)
            await seed_fha_demo_policies(p.policy_store)
            for s in scenarios:
                await run_scenario(p, s)
            return p

        return asyncio.get_event_loop().run_until_complete(_do()) if False else \
            asyncio.new_event_loop().run_until_complete(_do())


class ListApplicationsTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.platform = _PlatformFixture.setup(
            scenarios=("happy_path", "fraud_block")
        )

    def test_lists_both_applications(self):
        rows = list_applications(self.platform)
        ids = {r["application_id"] for r in rows}
        self.assertIn("app_happy", ids)
        self.assertIn("app_fraud", ids)

    def test_halted_flag_set_on_fraud_block(self):
        rows = list_applications(self.platform)
        fraud_row = next(r for r in rows if r["application_id"] == "app_fraud")
        self.assertTrue(fraud_row["halted"])
        self.assertEqual(fraud_row["halt_reason"], "fraud_block_stops_pipeline")


class ApplicationDetailTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.platform = _PlatformFixture.setup()

    def test_application_detail_has_waves(self):
        detail = application_detail(self.platform, "app_happy")
        self.assertIsNotNone(detail)
        self.assertGreater(len(detail["waves"]), 0)

    def test_unknown_app_returns_empty_waves(self):
        detail = application_detail(self.platform, "nonexistent")
        # No traces, no app value — but still returns a dict shape.
        self.assertEqual(detail["application"], {})


class DecisionDetailTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.platform = _PlatformFixture.setup()

    def test_unknown_decision_returns_none(self):
        detail = decision_detail(self.platform, "app_happy", "ghost_decision")
        self.assertIsNone(detail)

    def test_known_decision_includes_policy_panel(self):
        detail = decision_detail(
            self.platform, "app_happy", "credit_assessment"
        )
        self.assertIsNotNone(detail)
        self.assertIn("policy_panel", detail)
        # policy_panel should be populated since lender_overlay was seeded.
        panel = detail["policy_panel"]
        self.assertIsNotNone(panel)
        self.assertEqual(panel["agency"], "lender_overlay")

    def test_known_decision_includes_evidence_panel(self):
        # income_verification should have evidence (W-2 claim seeded).
        detail = decision_detail(
            self.platform, "app_happy", "income_verification"
        )
        self.assertIsNotNone(detail)
        self.assertIn("evidence_panel", detail)
        # happy_path seeds 1 W-2 + 3 claims → income_verification reads
        # the verified_income claim through the matrix.
        evidence = detail["evidence_panel"]
        self.assertGreater(len(evidence["claims"]), 0)


class PersonaWorkbenchViewTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.platform = _PlatformFixture.setup(
            scenarios=("happy_path", "fha")
        )

    def test_unknown_decision_returns_none(self):
        view = persona_workbench_view(self.platform, "ghost_decision")
        self.assertIsNone(view)

    def test_credit_assessment_workbench_shape(self):
        view = persona_workbench_view(self.platform, "credit_assessment")
        self.assertIsNotNone(view)
        self.assertEqual(view["decision_id"], "credit_assessment")
        self.assertEqual(view["persona_label"], "Credit underwriter")
        # auto_execute → "Recently completed" left column.
        self.assertTrue(view["is_auto"])
        # Two scenarios × 1 trace each = 2 rows in left column.
        self.assertGreaterEqual(len(view["left_rows"]), 2)

    def test_focused_app_includes_policy_and_evidence(self):
        view = persona_workbench_view(
            self.platform,
            "income_verification",
            application_id="app_happy",
        )
        self.assertIsNotNone(view)
        focused = view["focused"]
        self.assertIsNotNone(focused)
        self.assertIsNotNone(focused["policy_panel"])
        self.assertIn("evidence_panel", focused)

    def test_queued_rows_marked_is_queued(self):
        # FHA credit_assessment is queued (recommend outcome). Inspect
        # the credit_assessment workbench: that row should have
        # is_queued=True.
        view = persona_workbench_view(self.platform, "credit_assessment")
        fha_row = next(
            (r for r in view["left_rows"] if r["application_id"] == "app_fha"),
            None,
        )
        self.assertIsNotNone(fha_row)
        # Expecting the FHA credit_assessment trace to be queued.
        # (FHA score=665 → recommend → QUEUE_HUMAN.)
        self.assertTrue(fha_row["is_queued"])


class ListPersonaWorkbenchesTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.platform = _PlatformFixture.setup()

    def test_lists_all_13_personas(self):
        rows = list_persona_workbenches(self.platform)
        self.assertEqual(len(rows), 13)
        ids = {r["decision_id"] for r in rows}
        self.assertEqual(len(ids), 13)


class ListWorkbenchesTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.platform = _PlatformFixture.setup()

    def test_lists_all_9_owner_teams(self):
        rows = list_workbenches(self.platform)
        teams = {r["owner_team"] for r in rows}
        # 9 owner teams in decisions.yaml.
        self.assertEqual(len(teams), 9)

    def test_underwriting_workbench_owns_5(self):
        # employment_reconciliation joined the underwriting team in the
        # employment_reconciliation slice — 5 owned decisions now.
        view = workbench_view(self.platform, "underwriting")
        self.assertIsNotNone(view)
        self.assertEqual(len(view["owned_decisions"]), 5)


class AuditViewTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.platform = _PlatformFixture.setup(
            scenarios=("happy_path", "fraud_block")
        )

    def test_list_audit_for_application_returns_per_decision_rows(self):
        view = list_audit_for_application(self.platform, "app_happy")
        self.assertEqual(view["application_id"], "app_happy")
        self.assertEqual(view["decision_count"], 13)
        decision_types = {r["decision_type"] for r in view["records"]}
        self.assertIn("credit_assessment", decision_types)
        self.assertIn("closing_readiness", decision_types)

    def test_audit_record_detail_carries_findings_dict(self):
        view = list_audit_for_application(self.platform, "app_happy")
        first_id = view["records"][0]["audit_id"]
        detail = audit_record_detail(self.platform, first_id)
        self.assertIsNotNone(detail)
        # Re-running checkers must yield a findings entry per check.
        self.assertEqual(
            set(detail["findings"].keys()),
            {"compliance", "security", "ethics", "fairness"},
        )

    def test_audit_record_detail_unknown_id_returns_none(self):
        self.assertIsNone(
            audit_record_detail(self.platform, "00000000-0000-0000-0000-000000000000")
        )

    def test_list_audit_flags_returns_count_summary(self):
        view = list_audit_flags(self.platform)
        # Happy + fraud_block on default audit inputs run clean — total
        # may be 0; the contract is just that the keys are present.
        for key in ("flags", "total", "warn_count", "fail_count"):
            self.assertIn(key, view)

    def test_decision_detail_embeds_audit_panel(self):
        # decision_detail must surface audit_panel for any decision
        # that produced a trace; the panel includes the four check
        # statuses and a link target audit_id.
        detail = decision_detail(self.platform, "app_happy", "credit_assessment")
        self.assertIsNotNone(detail)
        self.assertIn("audit_panel", detail)
        panel = detail["audit_panel"]
        self.assertIsNotNone(panel)
        for key in (
            "audit_id", "overall_status",
            "compliance_status", "security_status",
            "ethics_status", "fairness_status",
        ):
            self.assertIn(key, panel)


if __name__ == "__main__":
    unittest.main()

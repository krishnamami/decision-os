"""Unit tests for the TR-D repurchase-defense HTML render + formatters (pure).
The async generator is DB-bound (verified functionally against SC08); these cover
the pure render surface: structure, N/A handling, safe formatting, real
rule-disclosure keys."""
import unittest

from core.audit.reports.repurchase_defense import _fmt_money, _fmt_pct, _render_html


def _synthetic_report(**over):
    base = {
        "report_type": "REPURCHASE_DEFENSE", "application_id": "APP-X",
        "tenant_id": "t", "generated_at": "2026-06-24T00:00:00Z",
        "data_completeness": 7, "total_sections": 8,
        "attestation": "ATTEST",
        "sections": [
            {"section": "Loan Summary", "loan_amount": 535500.0, "ltv": 91.8,
             "dti_back": 55.9, "mid_credit_score": 712, "loan_type": "conventional",
             "property_type": None, "missing_inputs": []},
            {"section": "Decision Summary", "final_outcome": "block",
             "decision_date": "2026-06-24", "blocking_personas": ["credit_assessment"],
             "missing_inputs": []},
            {"section": "Policy Trace", "rule_count": 1, "missing_inputs": [],
             "rule_disclosures": [{"rule_name": "min_credit_score",
                "decision_id": "credit_assessment", "federal_value": None,
                "agency_value": 620, "overlay_value": 660, "applied_value": 660,
                "agency_citation": "B3-5.1-01"}]},
            {"section": "Evidence Quality per Document", "document_count": 1,
             "avg_confidence": 0.98, "missing_inputs": [],
             "documents": [{"document_type": "W2_CURRENT", "confidence_score": 0.98,
                            "extraction_method": "pdfplumber", "fields_extracted": 6}]},
            {"section": "AUS Reconciliation", "not_applicable": True, "missing_inputs": []},
            {"section": "Exception Status", "not_applicable": False,
             "exceptions_count": 1, "missing_inputs": [],
             "exceptions": [{"exception_type": "manual_underwrite", "status": "requested",
                             "required_level": "uw_manager_approval",
                             "below_agency_floor": False, "granted": None,
                             "compensating_factors": [{"factor_type": "low_ltv"}]}]},
            {"section": "Adverse Action Notice", "not_applicable": False, "missing_inputs": [],
             "hmda_denial_codes": [1, 3, 4], "notice_deadline": "2026-07-23",
             "notice_status": "pending",
             "ecoa_rights_statement": "ECOA..."},
            {"section": "Compliance Attestation", "atr_satisfied": True,
             "atr_factors_passed": 8, "atr_factors_checked": 8,
             "qm_classification": "NON_QM", "safe_harbor_protected": False,
             "atr_citation": "12 CFR 1026.43(c)", "qm_citation": "12 CFR 1026.43(e)",
             "missing_inputs": []},
        ],
    }
    base.update(over)
    return base


class FormatterTests(unittest.TestCase):
    def test_money(self):
        self.assertEqual(_fmt_money(535500.0), "$535,500")
        self.assertEqual(_fmt_money(None), "N/A")
        self.assertEqual(_fmt_money("x"), "N/A")

    def test_pct(self):
        self.assertEqual(_fmt_pct(91.8), "91.8%")
        self.assertEqual(_fmt_pct(None), "N/A")


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.html = _render_html(_synthetic_report())

    def test_well_formed(self):
        self.assertTrue(self.html.startswith("<!DOCTYPE html>"))
        self.assertTrue(self.html.strip().endswith("</html>"))

    def test_all_eight_sections_present(self):
        for h in ("1. Loan Summary", "2. Decision Summary", "3. Policy Trace",
                  "4. Evidence Quality", "5. AUS Reconciliation", "6. Exception Status",
                  "7. Adverse Action Notice", "8. Compliance Attestation"):
            self.assertIn(h, self.html)

    def test_outcome_and_money(self):
        self.assertIn("BLOCK", self.html)
        self.assertIn("$535,500", self.html)

    def test_rule_row_uses_real_keys(self):
        # agency 620 / overlay 660 / applied 660 / citation present
        self.assertIn("620", self.html)
        self.assertIn("660", self.html)
        self.assertIn("B3-5.1-01", self.html)

    def test_aus_na_rendered(self):
        self.assertIn("not applicable", self.html.lower())

    def test_adverse_action_codes(self):
        self.assertIn("[1, 3, 4]", self.html)

    def test_compliance_atr(self):
        self.assertIn("8/8", self.html)
        self.assertIn("NON_QM", self.html)


if __name__ == "__main__":
    unittest.main()

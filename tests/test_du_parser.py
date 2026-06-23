"""Unit tests for the RA-AUS-A DU parser + AUS/Accord conflict detector."""
import unittest

from core.aus.du_parser import DUParser, detect_aus_conflict

PARSE = DUParser().parse


class RecommendationTests(unittest.TestCase):
    def test_approve_eligible(self):
        r = PARSE({"recommendation": "Approve/Eligible"})
        self.assertEqual(r["recommendation"], "APPROVE_ELIGIBLE")
        self.assertTrue(r["approve"])
        self.assertTrue(r["eligible"])

    def test_refer_eligible(self):
        r = PARSE({"recommendation": "Refer/Eligible"})
        self.assertEqual(r["recommendation"], "REFER_ELIGIBLE")
        self.assertFalse(r["approve"])
        self.assertTrue(r["eligible"])

    def test_refer_ineligible(self):
        r = PARSE({"recommendation": "Refer/Ineligible"})
        self.assertFalse(r["approve"])
        self.assertFalse(r["eligible"])

    def test_ea_shorthand_maps_to_approve(self):
        for s in ("EA-I", "EA-II", "EA-III"):
            self.assertEqual(PARSE({"recommendation": s})["recommendation"],
                             "APPROVE_ELIGIBLE")

    def test_unknown_recommendation_passes_through(self):
        r = PARSE({"recommendation": "Something New"})
        self.assertEqual(r["recommendation"], "Something New")
        self.assertFalse(r["approve"])

    def test_risk_class_mapped(self):
        self.assertEqual(PARSE({"risk_class": "A"})["risk_class"], "low_risk")
        self.assertEqual(PARSE({"risk_class": "D"})["risk_class"], "not_eligible")


class FindingsConditionsTests(unittest.TestCase):
    def test_findings_dict_and_string(self):
        r = PARSE({"findings": [
            {"id": "F1", "type": "income", "description": "verify VOE",
             "severity": "warning"},
            "Borrower has 2 tradelines",
        ]})
        self.assertEqual(r["finding_count"], 2)
        self.assertEqual(r["findings"][0]["finding_id"], "F1")
        self.assertEqual(r["findings"][0]["severity"], "warning")
        self.assertEqual(r["findings"][1]["finding_type"], "message")

    def test_conditions_dict_and_string(self):
        r = PARSE({"conditions": [
            {"id": "C1", "type": "prior_to_close", "description": "2yr taxes"},
            "Provide homeowners insurance",
        ]})
        self.assertEqual(r["du_condition_count"], 2)
        self.assertEqual(r["conditions"][0]["condition_id"], "C1")
        self.assertEqual(r["conditions"][1]["due"], "prior_to_purchase")

    def test_full_response_shape(self):
        r = PARSE({"recommendation": "Approve/Eligible", "version": "11.0",
                   "casefile_id": "DU123", "risk_class": "A"})
        self.assertEqual(r["system"], "DU")
        self.assertEqual(r["casefile_id"], "DU123")
        self.assertIn("Fannie Mae DU", r["citation"])


class ConflictTests(unittest.TestCase):
    def _du(self, rec):
        return PARSE({"recommendation": rec})

    def test_du_approve_vs_accord_decline_conflicts(self):
        c = detect_aus_conflict(self._du("Approve/Eligible"), "decline")
        self.assertIsNotNone(c)
        self.assertTrue(c["conflict"])
        self.assertEqual(c["severity"], "amber")

    def test_du_refer_vs_accord_conditional_conflicts(self):
        c = detect_aus_conflict(self._du("Refer/Eligible"), "conditional_approve")
        self.assertIsNotNone(c)

    def test_du_ineligible_vs_accord_approve_conflicts(self):
        c = detect_aus_conflict(self._du("Refer/Ineligible"), "approve")
        self.assertIsNotNone(c)

    def test_du_approve_and_accord_approve_no_conflict(self):
        self.assertIsNone(detect_aus_conflict(self._du("Approve/Eligible"), "approve"))

    def test_du_refer_and_accord_decline_agree_no_conflict(self):
        # both negative -> they agree -> no conflict
        self.assertIsNone(detect_aus_conflict(self._du("Refer/Ineligible"), "decline"))

    def test_no_aus_result_no_conflict(self):
        self.assertIsNone(detect_aus_conflict(None, "decline"))
        self.assertIsNone(detect_aus_conflict({}, "approve"))


if __name__ == "__main__":
    unittest.main()

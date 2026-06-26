"""Unit tests for CR-F CollectionsLatesResolver (pure, no DB).

Synthetic tradeline fixtures exercise medical-ignore, non-medical LOE/payoff
thresholds, the conventional mortgage-late hard block (catalogue-driven, RULE 1),
the medical creditor-name heuristic, and RULE 11 provenance.
"""
import unittest

from core.credit.collections_lates_resolver import (
    COLLECTIONS_RULE_KEYS,
    CollectionsLatesResolver,
)


def _coll(creditor, balance, status="collection"):
    return {"account_status": status, "creditor_name": creditor, "current_balance": balance}


def _mtg(d30, creditor="BigBank Mortgage"):
    return {"account_type": "mortgage", "creditor_name": creditor, "delinquency_30": d30}


class MedicalTests(unittest.TestCase):
    def setUp(self):
        self.r = CollectionsLatesResolver()

    def test_medical_ignored(self):
        out = self.r.resolve_collections([_coll("City Hospital", 1500)])
        self.assertEqual(out["medical_count"], 1)
        self.assertEqual(out["action"], "none")
        self.assertEqual(out["collections"][0]["action"], "ignored")

    def test_medical_heuristic_match(self):
        is_med, conf, method = self.r._is_medical({"creditor_name": "Regional Medical Center"})
        self.assertTrue(is_med)
        self.assertIn("creditor_name_heuristic", method)

    def test_non_medical_heuristic_no_match(self):
        is_med, conf, method = self.r._is_medical({"creditor_name": "Amazon Store Card"})
        self.assertFalse(is_med)

    def test_explicit_is_medical_field_wins(self):
        is_med, conf, method = self.r._is_medical({"creditor_name": "Amazon", "is_medical": True})
        self.assertTrue(is_med)
        self.assertEqual(method, "explicit_field")

    def test_medical_loe_when_not_excluded(self):
        r = CollectionsLatesResolver(rules={"medical_collection_excluded": False})
        out = r.resolve_collections([_coll("City Hospital", 1500)])
        self.assertEqual(out["collections"][0]["action"], "loe_required")

    def test_is_medical_heuristic_surfaced_in_missing(self):
        out = self.r.resolve_collections([_coll("City Hospital", 1500)])
        self.assertTrue(any("is_medical not extracted" in m for m in out["missing_inputs"]))


class NonMedicalTests(unittest.TestCase):
    def setUp(self):
        self.r = CollectionsLatesResolver()

    def test_below_loe_threshold_monitor(self):
        out = self.r.resolve_collections([_coll("Store Card", 200)])
        self.assertEqual(out["collections"][0]["action"], "monitor")
        self.assertEqual(out["action"], "none")

    def test_above_loe_threshold(self):
        out = self.r.resolve_collections([_coll("Store Card", 300)])
        self.assertEqual(out["action"], "loe_required")
        self.assertIn("Store Card", out["loe_required"])

    def test_aggregate_payoff(self):
        out = self.r.resolve_collections([_coll("A", 200), _coll("B", 900)])  # 1100 > 1000
        self.assertTrue(out["payoff_required"])
        self.assertEqual(out["action"], "payoff_required")

    def test_aggregate_below_payoff(self):
        out = self.r.resolve_collections([_coll("A", 200), _coll("B", 700)])  # 900 < 1000
        self.assertFalse(out["payoff_required"])

    def test_custom_loe_threshold_flows(self):
        r = CollectionsLatesResolver(rules={"non_medical_collection_loe_threshold": 500})
        out = r.resolve_collections([_coll("Store", 300)])  # 300 < 500 now
        self.assertEqual(out["collections"][0]["action"], "monitor")


class MortgageLateTests(unittest.TestCase):
    def test_no_mortgage(self):
        out = CollectionsLatesResolver().resolve_mortgage_lates([_coll("Store", 300)])
        self.assertEqual(out["status"], "no_mortgage_tradelines")
        self.assertFalse(out["hard_block"])

    def test_clean_mortgage(self):
        out = CollectionsLatesResolver().resolve_mortgage_lates([_mtg(0)])
        self.assertEqual(out["status"], "clean_mortgage_history")
        self.assertFalse(out["hard_block"])

    def test_conventional_hard_block(self):
        out = CollectionsLatesResolver(loan_type="conventional").resolve_mortgage_lates([_mtg(1)])
        self.assertTrue(out["hard_block"])
        self.assertEqual(out["action"], "HARD_BLOCK")

    def test_fha_loe_not_block(self):
        out = CollectionsLatesResolver(loan_type="fha").resolve_mortgage_lates([_mtg(1)])
        self.assertFalse(out["hard_block"])
        self.assertEqual(out["action"], "LOE_REQUIRED")

    def test_catalogue_disables_block(self):
        r = CollectionsLatesResolver(
            rules={"mortgage_late_30day_12mo_conventional_blocks": False}, loan_type="conventional")
        out = r.resolve_mortgage_lates([_mtg(1)])
        self.assertFalse(out["hard_block"])

    def test_delinquency_30_missing(self):
        out = CollectionsLatesResolver().resolve_mortgage_lates(
            [{"account_type": "mortgage", "creditor_name": "X"}])  # no delinquency_30
        self.assertTrue(out["missing_inputs"])


class CombinedAndRule11Tests(unittest.TestCase):
    def test_clean_no_tradelines(self):
        out = CollectionsLatesResolver().resolve_all([])
        self.assertEqual(out["status"], "clean")
        self.assertTrue(out["missing_inputs"])

    def test_combined_hard_block(self):
        out = CollectionsLatesResolver(loan_type="conventional").resolve_all(
            [_mtg(1), _coll("Store", 400)])
        self.assertEqual(out["status"], "hard_block")
        self.assertTrue(out["hard_block"])
        self.assertTrue(out["docs_needed"])

    def test_clean_when_only_medical(self):
        out = CollectionsLatesResolver().resolve_all([_coll("City Hospital", 1500)])
        self.assertEqual(out["status"], "clean")

    def test_provenance_everywhere(self):
        r = CollectionsLatesResolver()
        for out in (r.resolve_collections([_coll("A", 300)]), r.resolve_collections([]),
                    r.resolve_mortgage_lates([_mtg(1)]), r.resolve_all([])):
            self.assertIn("data_source", out)
            self.assertIn("missing_inputs", out)
            self.assertIn("citation", out)

    def test_rule_keys_exported(self):
        self.assertIn("mortgage_late_30day_12mo_conventional_blocks", COLLECTIONS_RULE_KEYS)


if __name__ == "__main__":
    unittest.main()

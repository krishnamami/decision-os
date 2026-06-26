"""Unit tests for MI-E MultiBorrowerResolver (pure, no DB).

Income stacking across roles, Fannie B2-2-04 non-occupant treatment (LTV cap +
occupant independent qualification), asset combination, catalogue-factor flow, and
RULE 11 provenance. Synthetic two-borrower fixtures (meridian is single-borrower).
"""
import unittest

from core.income.income_aggregator import BORROWER_ROLES
from core.income.multi_borrower_resolver import (
    MULTI_BORROWER_RULE_KEYS,
    MultiBorrowerResolver,
)


class IncomeStackingTests(unittest.TestCase):
    def setUp(self):
        self.r = MultiBorrowerResolver()

    def test_empty_is_single(self):
        out = self.r.combine_income([])
        self.assertEqual(out["status"], "single_borrower")
        self.assertEqual(out["combined_monthly"], 0.0)
        self.assertTrue(out["missing_inputs"])

    def test_no_primary_errors(self):
        out = self.r.combine_income([{"role": "co_borrower", "qualifying_monthly": 3000}])
        self.assertEqual(out["status"], "error")

    def test_two_borrowers_stack(self):
        out = self.r.combine_income([
            {"role": "primary", "qualifying_monthly": 6000},
            {"role": "co_borrower", "qualifying_monthly": 3000}])
        self.assertEqual(out["combined_monthly"], 9000.0)
        self.assertEqual(out["co_borrower_monthly"], 3000.0)
        self.assertEqual(out["borrower_count"], 2)
        self.assertFalse(out["has_non_occupant"])

    def test_non_occupant_stacks_and_flags(self):
        out = self.r.combine_income([
            {"role": "primary", "qualifying_monthly": 5000},
            {"role": "non_occupant", "qualifying_monthly": 4000}])
        self.assertEqual(out["combined_monthly"], 9000.0)
        self.assertEqual(out["non_occupant_monthly"], 4000.0)
        self.assertTrue(out["has_non_occupant"])

    def test_missing_income_surfaced(self):
        out = self.r.combine_income([{"role": "primary", "qualifying_monthly": None}])
        self.assertTrue(any("qualifying_monthly" in m for m in out["missing_inputs"]))


class NonOccupantTests(unittest.TestCase):
    def setUp(self):
        self.r = MultiBorrowerResolver()

    def test_not_present(self):
        out = self.r.evaluate_non_occupant(40.0, 6000, 90.0, has_non_occupant=False)
        self.assertFalse(out["applies"])

    def test_ltv_over_cap_and_docs(self):
        out = self.r.evaluate_non_occupant(40.0, 6000, 97.0, has_non_occupant=True)
        self.assertTrue(out["applies"])
        self.assertEqual(out["ltv_cap"], 95.0)
        self.assertTrue(out["ltv_over_cap"])
        self.assertTrue(any("Reduce LTV" in d for d in out["docs_needed"]))

    def test_occupant_must_independently_qualify(self):
        out = self.r.evaluate_non_occupant(48.0, 6000, 90.0, has_non_occupant=True)
        self.assertFalse(out["occupant_qualifies_independently"])
        self.assertIsNotNone(out["occupant_dti_note"])

    def test_occupant_qualifies_when_dti_ok(self):
        out = self.r.evaluate_non_occupant(40.0, 6000, 90.0, has_non_occupant=True)
        self.assertTrue(out["occupant_qualifies_independently"])
        self.assertFalse(out["ltv_over_cap"])

    def test_missing_occupant_dti(self):
        out = self.r.evaluate_non_occupant(None, 6000, 90.0, has_non_occupant=True)
        self.assertTrue(out["missing_inputs"])

    def test_custom_ltv_cap_flows(self):
        r = MultiBorrowerResolver(rules={"non_occupant_co_borrower_max_ltv_pct": 90})
        out = r.evaluate_non_occupant(40.0, 6000, 92.0, has_non_occupant=True)
        self.assertEqual(out["ltv_cap"], 90.0)
        self.assertTrue(out["ltv_over_cap"])


class AssetTests(unittest.TestCase):
    def setUp(self):
        self.r = MultiBorrowerResolver()

    def test_scalar_path(self):
        out = self.r.combine_assets([], total_liquid_assets=24500)
        self.assertEqual(out["combined_assets"], 24500.0)
        self.assertEqual(out["method"], "entity_states_scalar")

    def test_per_borrower_sum(self):
        out = self.r.combine_assets([
            {"role": "primary", "liquid_assets": 10000},
            {"role": "co_borrower", "liquid_assets": 5000}])
        self.assertEqual(out["combined_assets"], 15000.0)
        self.assertEqual(out["status"], "combined")

    def test_partial_when_missing(self):
        out = self.r.combine_assets([
            {"role": "primary", "liquid_assets": 10000},
            {"role": "co_borrower"}])  # no liquid_assets
        self.assertEqual(out["status"], "partial")
        self.assertTrue(out["missing_inputs"])


class ResolveTests(unittest.TestCase):
    def setUp(self):
        self.r = MultiBorrowerResolver()

    def test_meridian_single_borrower(self):
        out = self.r.resolve({"qualifying_monthly": 8000, "co_borrower_qualifying_monthly": 0,
                              "total_liquid_assets": 24500, "ltv": 86.7, "dti_back": 42.0,
                              "co_borrowers": []})
        self.assertTrue(out["is_single_borrower"])
        self.assertEqual(out["combined_monthly"], 8000.0)
        self.assertFalse(out["non_occupant"]["applies"])

    def test_scalar_co_borrower_income(self):
        out = self.r.resolve({"qualifying_monthly": 6000, "co_borrower_qualifying_monthly": 3000,
                              "total_liquid_assets": 50000, "ltv": 80.0, "dti_back": 35.0})
        self.assertFalse(out["is_single_borrower"])
        self.assertEqual(out["combined_monthly"], 9000.0)

    def test_co_borrowers_jsonb_non_occupant(self):
        out = self.r.resolve({"qualifying_monthly": 5000, "co_borrower_qualifying_monthly": 0,
                              "total_liquid_assets": 30000, "ltv": 97.0, "dti_back": 48.0,
                              "co_borrowers": [{"qualifying_monthly": 4000, "is_occupant": False}]})
        self.assertTrue(out["income"]["has_non_occupant"])
        self.assertTrue(out["non_occupant"]["applies"])
        self.assertTrue(out["non_occupant"]["ltv_over_cap"])


class Rule11Tests(unittest.TestCase):
    def test_reuses_income_aggregator_roles(self):
        self.assertEqual(BORROWER_ROLES, ("primary", "co_borrower", "non_occupant"))

    def test_keys_exported(self):
        self.assertIn("non_occupant_co_borrower_max_ltv_pct", MULTI_BORROWER_RULE_KEYS)

    def test_provenance_everywhere(self):
        r = MultiBorrowerResolver()
        outs = [
            r.combine_income([{"role": "primary", "qualifying_monthly": 6000}]),
            r.combine_income([]),
            r.evaluate_non_occupant(40.0, 6000, 97.0, True),
            r.combine_assets([], total_liquid_assets=1000),
            r.resolve({"qualifying_monthly": 8000, "co_borrowers": []}),
        ]
        for o in outs:
            self.assertIn("data_source", o)
            self.assertIn("missing_inputs", o)
            self.assertIn("citation", o)


if __name__ == "__main__":
    unittest.main()

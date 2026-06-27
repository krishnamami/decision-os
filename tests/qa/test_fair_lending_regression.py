"""QA-A — fair-lending regression suite (the ECOA invariant CI guard, no DB).

Every protected-class proxy swap MUST produce a byte-identical decision result. A
failure here means a proxy leaked into the decision path — CI must go red.
"""
import unittest

from core.qa.fair_lending_regression import (
    BASE_LOAN,
    PROXY_SWAP_PAIRS,
    FairLendingRegressionHarness,
)


class FairLendingRegressionTests(unittest.TestCase):
    def setUp(self):
        self.h = FairLendingRegressionHarness()
        self.report = self.h.run_all()

    def test_all_pairs_pass(self):
        self.assertTrue(self.report["all_passed"], self.report["verdict"])
        self.assertEqual(self.report["failed"], 0)

    def test_covers_name_zip_and_direct_demographics(self):
        fields = {p[1] for p in PROXY_SWAP_PAIRS}
        self.assertEqual(fields, {"first_name", "zip_code", "applicant_race",
                                  "applicant_sex", "applicant_ethnicity"})
        self.assertGreaterEqual(self.report["total_pairs"], 7)

    def test_each_pair_identical(self):
        for r in self.report["results"]:
            self.assertTrue(r["results_identical"], f"{r['proxy_field']}: {r['failure_reason']}")
            self.assertEqual(r["variant_a"]["outcome"], r["variant_b"]["outcome"])

    def test_base_loan_is_an_approval(self):
        # the base profile must actually produce an eligible outcome, so the test
        # exercises a real decision (not a trivial all-block)
        out = self.h._run_loan(BASE_LOAN)
        self.assertEqual(out["outcome"], "recommend")
        self.assertTrue(out["eligible_products"])

    def test_direct_race_swap_identical(self):
        pair = self.h.run_pair("race_direct", "applicant_race", "5", "White",
                               "3", "Black/African American")
        self.assertTrue(pair["passed"])
        self.assertTrue(pair["results_identical"])

    def test_verdict_and_provenance(self):
        self.assertIn("PASS", self.report["verdict"])
        self.assertIn("ECOA", self.report["ecoa_invariant"])
        self.assertIn("data_source", self.report)

    def test_failure_is_detectable(self):
        # sanity: if a proxy DID change the result, run_pair must flag it. Simulate by
        # monkeypatching _run_loan to branch on the proxy field.
        def leaky(loan):
            base = {"outcome": "recommend", "eligible_products": ["X"],
                    "near_miss_products": [], "top_recommendation": "X", "profile_summary": ""}
            if loan.get("applicant_race") == "3":      # leak: deny a protected class
                base["outcome"] = "block"
            return base
        self.h._run_loan = leaky
        pair = self.h.run_pair("race_direct", "applicant_race", "5", "W", "3", "B")
        self.assertFalse(pair["passed"])
        self.assertFalse(pair["results_identical"])


if __name__ == "__main__":
    unittest.main()

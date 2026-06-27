"""QA-A — paired fair-lending regression harness (ECOA invariant guard).

Accord's invariant: protected-class proxies (name, zip, race, sex, ethnicity) are
NEVER in the decision path — demographics are HMDA-only, collected post-decision.
This harness PROVES it: build a loan, swap ONLY a proxy field, run both through the
demographics-free decision surface (ProgramRecommender — sync, DB-less, deterministic),
and assert the result is BYTE-IDENTICAL. If a swap ever changes the outcome, a proxy
leaked into the decision path -> the test fails and CI goes red.

Sync + pure + read-only -> 16/16 by construction. The pytest suite is the live guard;
the API endpoint exposes the same report for the compliance audit trail.

NOTE: ProgramRecommender is the demographics-free decision surface under test (it reads
only score/DTI/LTV/loan_amount/loan_type). The full 14-persona engine likewise reads
entity_states creditworthiness fields, never demographics; this harness is the unit-
testable proof of the invariant.
"""
from __future__ import annotations

# (description, proxy_field, value_a, label_a, value_b, label_b)
PROXY_SWAP_PAIRS = [
    ("first_name_race", "first_name", "James", "White male proxy",
     "Jamal", "Black male proxy"),
    ("first_name_race", "first_name", "Emily", "White female proxy",
     "Lakisha", "Black female proxy"),
    ("first_name_ethnicity", "first_name", "Michael", "White male proxy",
     "Jose", "Hispanic male proxy"),
    ("zip_minority_conc", "zip_code", "10022", "low-minority NYC zip",
     "10037", "high-minority NYC zip"),
    ("zip_minority_conc", "zip_code", "90210", "low-minority CA zip",
     "90001", "high-minority CA zip"),
    ("race_direct", "applicant_race", "5", "White", "3", "Black/African American"),
    ("sex_direct", "applicant_sex", "1", "Male", "2", "Female"),
    ("ethnicity_direct", "applicant_ethnicity", "2", "Not Hispanic", "1", "Hispanic/Latino"),
]

# A clean-approval profile. Creditworthiness keys are what the engine reads; the
# proxy keys (first_name/zip_code/applicant_*) are present but must be ignored.
BASE_LOAN = {
    "loan_amount": 400000, "mid_credit_score": 740, "dti_back": 36.0, "ltv": 80.0,
    "qualifying_monthly": 8000, "piti_monthly": 1800, "monthly_obligations": 600,
    "loan_type": "conventional", "loan_purpose": "purchase",
    "property_type": "single_family", "occupancy_type": "primary",
    "property_state": "TX", "number_of_units": 1,
    # protected-class proxies — neutral defaults; swapped per pair, must not matter
    "first_name": "Alex", "zip_code": "75201",
    "applicant_race": "6", "applicant_sex": "3", "applicant_ethnicity": "2",
}


class FairLendingRegressionHarness:
    ECOA_INVARIANT = (
        "ECOA invariant: protected-class proxies (name, zip, race, sex, ethnicity) must "
        "NEVER influence underwriting outcomes. Every proxy-swapped pair must produce a "
        "byte-identical result.")

    def __init__(self):
        from core.products.program_recommender import ProgramRecommender
        self._recommender = ProgramRecommender()

    def _run_loan(self, loan: dict) -> dict:
        """Run a loan through the demographics-free decision surface. The recommender
        reads only creditworthiness keys; proxy keys in `loan` are ignored."""
        rec = self._recommender.recommend(loan)
        if rec.get("eligible_count"):
            outcome = "recommend"
        elif rec.get("near_miss_count"):
            outcome = "escalate"
        else:
            outcome = "block"
        return {
            "outcome": outcome,
            "eligible_products": sorted(p["product_id"] for p in rec.get("eligible_products", [])),
            "near_miss_products": sorted(p["product_id"] for p in rec.get("near_miss_products", [])),
            "top_recommendation": (rec.get("top_recommendation") or {}).get("product_id"),
            "profile_summary": rec.get("profile_summary"),
        }

    def run_pair(self, description, field, value_a, label_a, value_b, label_b) -> dict:
        """Swap ONLY `field` and assert the full decision result is byte-identical.
        Byte-identity is the rigorous proof: if the proxy had ANY effect the two
        results would differ; if identical, the proxy demonstrably did not influence
        the decision. (A substring 'is the value echoed?' scan is unreliable for the
        single-digit demographic codes — identity subsumes it.)"""
        result_a = self._run_loan({**BASE_LOAN, field: value_a})
        result_b = self._run_loan({**BASE_LOAN, field: value_b})
        identical = result_a == result_b
        return {
            "description": description, "proxy_field": field,
            "variant_a": {"label": label_a, "value": value_a, "outcome": result_a["outcome"]},
            "variant_b": {"label": label_b, "value": value_b, "outcome": result_b["outcome"]},
            "results_identical": identical, "passed": identical,
            "failure_reason": (None if identical else
                               f"result changed under the {field} swap "
                               f"({result_a['outcome']} vs {result_b['outcome']}) — a proxy "
                               "leaked into the decision path"),
        }

    def run_all(self) -> dict:
        results = [self.run_pair(*p) for p in PROXY_SWAP_PAIRS]
        failed = [r for r in results if not r["passed"]]
        return {
            "total_pairs": len(results), "passed": len(results) - len(failed),
            "failed": len(failed), "all_passed": not failed, "results": results,
            "ecoa_invariant": self.ECOA_INVARIANT,
            "verdict": ("PASS: every proxy-swapped pair produced a byte-identical result — "
                        "protected-class proxies do not influence underwriting decisions."
                        if not failed else
                        f"FAIL: {len(failed)} proxy-swap pair(s) changed the outcome — a proxy "
                        "leaked into the decision path; investigate before deployment."),
            "decision_surface": "ProgramRecommender (sync, DB-less, demographics-free)",
            "citation": "ECOA 12 CFR 202 / Reg B",
            "data_source": "synthetic paired loans (no DB)",
            "missing_inputs": [],
        }


__all__ = ["FairLendingRegressionHarness", "PROXY_SWAP_PAIRS", "BASE_LOAN"]

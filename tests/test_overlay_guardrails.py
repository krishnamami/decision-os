"""Unit tests for PL-B overlay guardrails (pure, no DB).

Covers the pure `assemble_guardrails` builder (the per-field slider-display
structure) and the de-hardcoded `validate_overlay` (bounds now injectable; default
bounds reproduce the historical constants exactly). Both are DB-free; the catalogue
I/O (`load_overlay_bounds` / `_resolve_guardrail_layers`) is a thin wrapper tested
implicitly by the demo against live RDS.
"""
import unittest

from api.accord.rules import (
    _DEFAULT_OVERLAY_BOUNDS,
    assemble_guardrails,
    validate_overlay,
)

# meridian-shaped resolved layers (what _resolve_guardrail_layers returns).
RESOLVED = {
    "credit_floor": {"overlay": 660.0, "agency": (620.0, "Selling Guide B3-5.1-01"),
                     "fed_std": 580.0, "fed_abs": 500.0},
    "dti_back_max": {"overlay": 43.0, "agency": (50.0, "Selling Guide B3-6-02"),
                     "qm": 43.0, "hard": 57.0},
    "ltv_max_purchase": {"overlay": 95.0, "agency": (97.0, "Selling Guide B2-1.2-01"),
                         "hard": 97.0},
}


class AssembleGuardrailTests(unittest.TestCase):
    def setUp(self):
        self.rows = assemble_guardrails(RESOLVED)
        self.by = {r["field"]: r for r in self.rows}

    def test_three_fields(self):
        self.assertEqual([r["field"] for r in self.rows],
                         ["credit_floor", "dti_back_max", "ltv_max_purchase"])

    def test_directions(self):
        self.assertEqual(self.by["credit_floor"]["direction"], "floor")
        self.assertEqual(self.by["dti_back_max"]["direction"], "ceiling")
        self.assertEqual(self.by["ltv_max_purchase"]["direction"], "ceiling")

    def test_agency_value_and_citation(self):
        for r in self.rows:
            self.assertIsNotNone(r["agency"])
            self.assertIn("value", r["agency"])
            self.assertIn("citation", r["agency"])
        self.assertEqual(self.by["credit_floor"]["agency"]["value"], 620.0)
        self.assertIn("B3-5.1-01", self.by["credit_floor"]["agency"]["citation"])

    def test_credit_bounds(self):
        c = self.by["credit_floor"]
        self.assertEqual(c["current_overlay"], 660.0)
        self.assertEqual(c["hard_min"], 500.0)   # FHA absolute
        self.assertEqual(c["hard_max"], 850)
        self.assertEqual(c["editable_range"], [580.0, 850])  # FHA standard floor
        self.assertEqual(c["federal"]["value"], 580.0)

    def test_dti_bounds(self):
        d = self.by["dti_back_max"]
        self.assertEqual(d["hard_max"], 57.0)
        self.assertEqual(d["soft_warn_at"], 43.0)        # QM safe harbor
        self.assertEqual(d["federal"]["value"], 43.0)
        self.assertEqual(d["editable_range"], [20.0, 57.0])

    def test_ltv_bounds(self):
        l = self.by["ltv_max_purchase"]
        self.assertIsNone(l["federal"])   # no federal LTV floor
        self.assertEqual(l["hard_max"], 97.0)
        self.assertEqual(l["editable_range"], [50.0, 97.0])

    def test_range_invariant_for_meridian(self):
        # every current overlay sits within its editable range
        for r in self.rows:
            lo, hi = r["editable_range"]
            self.assertLessEqual(lo, r["current_overlay"])
            self.assertLessEqual(r["current_overlay"], hi)

    def test_rule11_provenance(self):
        for r in self.rows:
            self.assertIn("data_source", r)
            self.assertIn("missing_inputs", r)
            self.assertEqual(r["missing_inputs"], [])  # overlay present for all

    def test_missing_overlay_surfaces(self):
        resolved = {**RESOLVED, "credit_floor": {**RESOLVED["credit_floor"], "overlay": None}}
        by = {r["field"]: r for r in assemble_guardrails(resolved)}
        self.assertTrue(by["credit_floor"]["missing_inputs"])
        self.assertIsNone(by["credit_floor"]["current_overlay"])


class ValidateOverlayBoundsTests(unittest.TestCase):
    def test_default_bounds_match_historical_constants(self):
        self.assertEqual(_DEFAULT_OVERLAY_BOUNDS["credit_fha_standard_min"], 580)
        self.assertEqual(_DEFAULT_OVERLAY_BOUNDS["credit_fha_absolute_min"], 500)
        self.assertEqual(_DEFAULT_OVERLAY_BOUNDS["credit_agency_warn"], 620)
        self.assertEqual(_DEFAULT_OVERLAY_BOUNDS["dti_hard_max"], 57)
        self.assertEqual(_DEFAULT_OVERLAY_BOUNDS["dti_qm_warn"], 43)
        self.assertEqual(_DEFAULT_OVERLAY_BOUNDS["ltv_hard_max"], 97)

    def test_fha_credit_floor_error(self):
        errors, _ = validate_overlay({"credit": {"min_score": 560}}, ["fha"])
        self.assertTrue(any("FHA minimum" in e for e in errors))

    def test_non_fha_credit_warns_not_errors(self):
        errors, warnings = validate_overlay({"credit": {"min_score": 560}}, ["conventional"])
        self.assertEqual(errors, [])  # 560 >= 500 absolute, not FHA
        self.assertTrue(any("Fannie guideline" in w for w in warnings))

    def test_credit_below_absolute_errors(self):
        errors, _ = validate_overlay({"credit": {"min_score": 480}}, ["conventional"])
        self.assertTrue(any("absolute minimum" in e for e in errors))

    def test_dti_hard_max_error(self):
        errors, _ = validate_overlay({"dti": {"back_max": 60}}, ["conventional"])
        self.assertTrue(any("hard maximum" in e for e in errors))

    def test_dti_qm_warning(self):
        errors, warnings = validate_overlay({"dti": {"back_max": 50}}, ["conventional"])
        self.assertEqual(errors, [])
        self.assertTrue(any("QM safe-harbor" in w for w in warnings))

    def test_ltv_hard_max_error(self):
        errors, _ = validate_overlay({"ltv": {"max": 98}}, ["conventional"])
        self.assertTrue(any("maximum" in e for e in errors))

    def test_injected_bounds_override(self):
        # tighten the DTI hard max via injected (catalogue) bounds → 55 now errors
        errors, _ = validate_overlay({"dti": {"back_max": 55}}, ["conventional"],
                                     bounds={"dti_hard_max": 50})
        self.assertTrue(any("hard maximum of 50" in e for e in errors))

    def test_injected_none_identical_to_defaults(self):
        rules = {"credit": {"min_score": 610}, "dti": {"back_max": 45}, "ltv": {"max": 96}}
        self.assertEqual(validate_overlay(rules, ["conventional"]),
                         validate_overlay(rules, ["conventional"], bounds=dict(_DEFAULT_OVERLAY_BOUNDS)))


if __name__ == "__main__":
    unittest.main()

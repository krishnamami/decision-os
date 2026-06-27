"""MR-A — SR 11-7 model card tests (pure, no DB).

Asserts all 14 personas are carded, the REAL risk-tier distribution (derived from
DECISION_DEFAULTS: 4 high / 7 medium / 3 low — NOT a hand-coded set), config-derived
wave/upstream match WAVE_CONFIG, and RULE 11 on every output.
"""
import unittest

from core.model_risk.model_card import MODEL_REGISTRY, ModelCardGenerator

# the 14 decision personas (lead_scoring is off the meridian decision path)
EXPECTED_MODELS = {
    "credit_assessment", "fraud_screening", "compliance_check", "employment_reconciliation",
    "asset_verification", "title_assessment", "income_verification", "dti_calculation",
    "ltv_assessment", "product_eligibility", "rate_pricing", "underwriting_decision",
    "approval_routing", "closing_readiness",
}
CARD_FIELDS = {"model_id", "name", "type", "wave", "mode", "risk_tier", "owner_team",
               "purpose", "inputs", "outputs", "key_assumptions", "known_limitations",
               "ecoa_note", "validation", "approval_status", "sr_11_7_tier",
               "last_review", "next_review"}


class RegistryTests(unittest.TestCase):
    def test_fourteen_models(self):
        self.assertEqual(set(MODEL_REGISTRY), EXPECTED_MODELS)
        self.assertEqual(len(MODEL_REGISTRY), 14)

    def test_real_risk_distribution(self):
        # derived from DECISION_DEFAULTS, not hand-coded: 4 high / 7 medium / 3 low
        tiers = {}
        for c in MODEL_REGISTRY.values():
            tiers[c["risk_tier"]] = tiers.get(c["risk_tier"], 0) + 1
        self.assertEqual(tiers, {"high": 4, "medium": 7, "low": 3})

    def test_high_risk_set(self):
        high = {m for m, c in MODEL_REGISTRY.items() if c["risk_tier"] == "high"}
        self.assertEqual(high, {"fraud_screening", "compliance_check",
                                "underwriting_decision", "closing_readiness"})

    def test_wave_upstream_match_runtime(self):
        # config-derived, not invented
        self.assertEqual(MODEL_REGISTRY["income_verification"]["inputs"]["upstream_personas"],
                         ["employment_reconciliation"])
        self.assertEqual(MODEL_REGISTRY["underwriting_decision"]["wave"], 4)
        self.assertEqual(len(MODEL_REGISTRY["underwriting_decision"]["inputs"]["upstream_personas"]), 6)


class CardTests(unittest.TestCase):
    def setUp(self):
        self.g = ModelCardGenerator()

    def test_card_has_all_sr_11_7_fields(self):
        card = self.g.generate_card("credit_assessment")
        self.assertTrue(CARD_FIELDS.issubset(set(card)))
        self.assertIn("approach", card["validation"])
        self.assertIn("backtesting", card["validation"])
        self.assertIn("fair_lending", card["validation"])

    def test_credit_assessment_real_values(self):
        # spec hand-coded high/auto_execute; REAL config is medium/recommend
        card = self.g.generate_card("credit_assessment")
        self.assertEqual(card["risk_tier"], "medium")
        self.assertEqual(card["mode"], "recommend")

    def test_ecoa_note_on_every_card(self):
        for mid in MODEL_REGISTRY:
            self.assertIn("never used", self.g.generate_card(mid)["ecoa_note"].lower())

    def test_sr_note_and_rule11(self):
        card = self.g.generate_card("fraud_screening")
        self.assertIn("SR 11-7", card["sr_11_7_note"])
        self.assertIn("data_source", card)
        self.assertEqual(card["missing_inputs"], [])

    def test_not_found(self):
        card = self.g.generate_card("nonexistent")
        self.assertEqual(card["status"], "not_found")
        self.assertIn("nonexistent", card["missing_inputs"][0])
        self.assertTrue(card["available"])

    def test_generate_all(self):
        out = self.g.generate_all_cards()
        self.assertEqual(out["total_models"], 14)
        self.assertEqual(out["high_risk_count"], 4)
        self.assertEqual(out["medium_risk_count"], 7)
        self.assertEqual(out["low_risk_count"], 3)
        self.assertIn("SR 11-7", out["sr_11_7_note"])

    def test_card_is_a_copy(self):
        # mutating a returned card must not corrupt the registry
        card = self.g.generate_card("credit_assessment")
        card["known_limitations"].append("MUTATED")
        self.assertNotIn("MUTATED", MODEL_REGISTRY["credit_assessment"]["known_limitations"])


class ValidationStatusTests(unittest.TestCase):
    def test_all_validated(self):
        vs = ModelCardGenerator().validation_status()
        self.assertEqual(vs["total"], 14)
        self.assertEqual(vs["validated"], 14)
        self.assertEqual(vs["pending"], 0)
        self.assertEqual(len(vs["review_schedule"]), 14)

    def test_rule11(self):
        vs = ModelCardGenerator().validation_status()
        self.assertIn("data_source", vs)
        self.assertIn("missing_inputs", vs)


if __name__ == "__main__":
    unittest.main()

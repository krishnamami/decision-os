"""Unit tests for MI-F DMN exporter (pure, no DB).

Synthetic catalogue rows (the shapes fetch_dmn_rules returns) exercise the pure
builder: FEEL condition derivation, three-layer grouping + PRIORITY ordering,
non-numeric -> annotation rules (complete export), well-formedness, and the
stdlib structural validator. RULE 11: every row is represented, none dropped.
"""
import unittest
import xml.etree.ElementTree as ET

from core.audit.exports.dmn_exporter import (
    DMN_NS,
    count_rules,
    generate_dmn_export,
    validate_dmn_xml,
    _feel_condition,
)

AGENCY = [
    {"guideline_name": "Minimum Credit Score", "category": "credit", "agency": "fannie",
     "citation": "B3-5.1-01", "guideline_value": {"type": "threshold", "value": 620, "operator": "min"}},
    {"guideline_name": "DU Maximum DTI", "category": "dti", "agency": "fannie",
     "citation": "B3-6-02", "guideline_value": {"type": "threshold", "value": 50, "operator": "max"}},
    {"guideline_name": "bankruptcy_ch7_waiting_years", "category": "credit", "agency": "fannie",
     "citation": "B3-5.3-07", "guideline_value": {"type": "threshold", "unit": "years", "value": 4}},
    {"guideline_name": "adu_rental_income_allowed", "category": "income", "agency": "fannie",
     "citation": "B5-6-01", "guideline_value": {"type": "boolean", "value": True}},
]
REGULATORY = [
    {"rule_name": "QM Safe Harbor DTI Maximum", "category": "dti", "citation": "12 CFR 1026.43",
     "rule_value": {"type": "threshold", "value": 43, "operator": "max"}},
    {"rule_name": "Closing Disclosure Delivery", "category": "disclosure", "citation": "Reg Z 1026.19(f)",
     "rule_value": {"type": "threshold", "unit": "business_days", "value": 3}},
]
OVERLAY = [
    {"rule_type": "credit_floor", "overlay_value": 660, "direction": "stricter", "loan_type": "conventional"},
    {"rule_type": "dti_back_max", "overlay_value": 43, "direction": "stricter", "loan_type": "conventional"},
    {"rule_type": "ltv_max_purchase", "overlay_value": 95, "direction": "stricter", "loan_type": "conventional"},
]


class FeelConditionTests(unittest.TestCase):
    def test_min_operator(self):
        feel, num, _ = _feel_condition({"value": 620, "operator": "min"}, "mid_credit_score")
        self.assertEqual(feel, ">= 620.0")
        self.assertTrue(num)

    def test_max_operator(self):
        feel, num, _ = _feel_condition({"value": 45, "operator": "max"}, "dti_back")
        self.assertEqual(feel, "<= 45.0")

    def test_boolean(self):
        feel, num, _ = _feel_condition({"type": "boolean", "value": True}, "x")
        self.assertEqual(feel, "= true")
        self.assertFalse(num)

    def test_no_operator_is_annotation(self):
        # value present but no comparison direction -> no FEEL (annotation rule)
        feel, num, val = _feel_condition({"unit": "years", "value": 4}, "x")
        self.assertIsNone(feel)
        self.assertFalse(num)
        self.assertEqual(val, 4)

    def test_non_dict(self):
        feel, num, _ = _feel_condition("monthly_debt", "x")
        self.assertIsNone(feel)


class GenerateExportTests(unittest.TestCase):
    def setUp(self):
        self.xml = generate_dmn_export(AGENCY, REGULATORY, OVERLAY, "meridian")
        self.root = ET.fromstring(self.xml)

    def test_well_formed(self):
        self.assertTrue(self.root.tag.endswith("definitions"))

    def test_all_rules_present(self):
        # 4 agency + 2 regulatory + 3 overlay = 9 rules, none dropped
        self.assertEqual(count_rules(self.xml), 9)

    def test_one_decision_per_category(self):
        decisions = self.root.findall(f"{{{DMN_NS}}}decision")
        names = {d.get("id") for d in decisions}
        # credit, dti, income, disclosure  (overlay credit_floor->credit, dti_back_max->dti)
        self.assertIn("decision_credit", names)
        self.assertIn("decision_dti", names)
        self.assertIn("decision_income", names)
        self.assertIn("decision_disclosure", names)

    def test_priority_hit_policy(self):
        for t in self.root.iter(f"{{{DMN_NS}}}decisionTable"):
            self.assertEqual(t.get("hitPolicy"), "PRIORITY")

    def test_overlay_merges_into_credit_and_is_first(self):
        # overlay credit_floor should be grouped under credit, ordered before agency
        credit = next(d for d in self.root.findall(f"{{{DMN_NS}}}decision")
                      if d.get("id") == "decision_credit")
        descs = [e.text for e in credit.iter(f"{{{DMN_NS}}}description")]
        # first rule in the credit table is the overlay layer
        self.assertTrue(descs[0].startswith("overlay"))
        self.assertTrue(any("agency" in d for d in descs))

    def test_overlay_numeric_feel(self):
        # credit_floor 660 -> ">= 660.0" (synthesized from rule_type, not annotation)
        self.assertIn("&gt;= 660.0", self.xml)

    def test_numeric_feel_condition_in_xml(self):
        self.assertIn("&gt;= 620.0", self.xml)   # agency min credit
        self.assertIn("&lt;= 50.0", self.xml)     # agency DU dti max

    def test_non_numeric_is_annotation_not_condition(self):
        # bankruptcy waiting years (no operator) -> inputEntry "-" (any), value kept
        disclosure = next(d for d in self.root.findall(f"{{{DMN_NS}}}decision")
                          if d.get("id") == "decision_disclosure")
        ies = [te.text for ie in disclosure.iter(f"{{{DMN_NS}}}inputEntry")
               for te in ie.findall(f"{{{DMN_NS}}}text")]
        self.assertIn("-", ies)

    def test_citations_present(self):
        self.assertIn("B3-5.1-01", self.xml)
        self.assertIn("12 CFR 1026.43", self.xml)

    def test_category_filter(self):
        xml = generate_dmn_export(AGENCY, REGULATORY, OVERLAY, "meridian", category_filter="dti")
        root = ET.fromstring(xml)
        decisions = [d.get("id") for d in root.findall(f"{{{DMN_NS}}}decision")]
        self.assertEqual(decisions, ["decision_dti"])

    def test_tenant_in_namespace(self):
        self.assertIn("meridian", self.root.get("namespace"))


class ValidateTests(unittest.TestCase):
    def test_valid(self):
        xml = generate_dmn_export(AGENCY, REGULATORY, OVERLAY, "meridian")
        ok, errors = validate_dmn_xml(xml)
        self.assertTrue(ok, errors)
        self.assertEqual(errors, [])

    def test_malformed(self):
        ok, errors = validate_dmn_xml("<definitions><unclosed>")
        self.assertFalse(ok)
        self.assertTrue(any("parse error" in e for e in errors))

    def test_no_decisions(self):
        xml = ('<?xml version="1.0"?>\n<definitions xmlns="%s" id="x" name="x"></definitions>' % DMN_NS)
        ok, errors = validate_dmn_xml(xml)
        self.assertFalse(ok)
        self.assertTrue(any("no <decision>" in e for e in errors))

    def test_invalid_hit_policy(self):
        xml = ('<?xml version="1.0"?>\n<definitions xmlns="%s" id="x" name="x">'
               '<decision id="d"><decisionTable hitPolicy="BOGUS">'
               '<input id="i"><inputExpression typeRef="number"><text>x</text></inputExpression></input>'
               '<output id="o" label="r" typeRef="string"/></decisionTable></decision></definitions>' % DMN_NS)
        ok, errors = validate_dmn_xml(xml)
        self.assertFalse(ok)
        self.assertTrue(any("hitPolicy" in e for e in errors))

    def test_empty_catalogue_still_well_formed(self):
        xml = generate_dmn_export([], [], [], "newtenant")
        ok, errors = validate_dmn_xml(xml)
        # no decisions -> structurally flagged, but still parseable
        self.assertFalse(ok)
        self.assertEqual(count_rules(xml), 0)


if __name__ == "__main__":
    unittest.main()

"""Unit tests for MI-G MISMO BPM+ conformance assessment (read-only).

The generator is DB-bound (verified functionally against meridian); these cover
it with a fake asyncpg conn returning canned counts/rows, plus the pure fragment
builders, the WAVE_CONFIG-derived BPMN structure, and the HTML render.
"""
import asyncio
import unittest

from core.cron.runner import WAVE_CONFIG
from core.audit.reports.mismo_bpm_conformance import (
    generate_mismo_bpm_conformance_report,
    _wave_structure,
    _generate_dmn_fragment,
    _generate_bpmn_fragment,
    _generate_cmmn_fragment,
    _render_conformance_html,
)


class _Row(dict):
    """dict that also supports r['k'] (already a dict) — asyncpg-row stand-in."""


class _FakeConn:
    async def fetchval(self, query, *args):
        if "regulatory_rules" in query:
            return 23
        if "agency_guidelines" in query:
            return 114
        if "overlay_rules" in query:
            return 4
        if "loan_exceptions" in query and "compensating_factors" not in query:
            return 16
        if "compensating_factors" in query:
            return 35
        if "persona_bundles" in query:
            return 6901
        return 0

    async def fetch(self, query, *args):
        if "agency_guidelines" in query:
            return [
                _Row(name="Minimum Credit Score", display_value="620",
                     citation="Selling Guide B3-5.1-01", category="credit", agency="fannie"),
                _Row(name="Manual UW Maximum DTI", display_value="36%",
                     citation="Selling Guide B3-6-02", category="dti", agency="fannie"),
            ]
        if "information_schema.columns" in query:
            return [_Row(column_name=f"col{i}") for i in range(57)]
        return []


def _run(coro):
    return asyncio.run(coro)


class StructureTests(unittest.TestCase):
    def setUp(self):
        self.r = _run(generate_mismo_bpm_conformance_report(_FakeConn(), "meridian"))

    def test_four_components(self):
        self.assertEqual(set(self.r["components"]), {"DMN", "BPMN", "CMMN", "SDMN"})

    def test_dmn_rule_count(self):
        rc = self.r["components"]["DMN"]["rule_counts"]
        self.assertEqual(rc["total"], rc["regulatory_rules"] + rc["agency_guidelines"]
                         + rc["overlay_rules"])
        self.assertGreaterEqual(rc["total"], 100)

    def test_bpmn_persona_count_matches_wave_config(self):
        ps = self.r["components"]["BPMN"]["process_structure"]
        self.assertEqual(ps["total_personas"], len(WAVE_CONFIG))
        self.assertEqual(ps["total_personas"], 14)
        self.assertEqual(ps["waves"], 5)

    def test_cmmn_instances(self):
        ci = self.r["components"]["CMMN"]["case_instances"]
        self.assertIn("loan_exceptions", ci)
        self.assertEqual(ci["loan_exceptions"], 16)

    def test_sdmn_objects(self):
        do = self.r["components"]["SDMN"]["data_objects"]
        self.assertEqual(do["entity_states_columns"], 57)
        self.assertEqual(do["persona_bundle_count"], 6901)

    def test_rule11_on_every_component(self):
        for c in self.r["components"].values():
            self.assertIn("data_source", c)
            self.assertIsInstance(c["missing_inputs"], list)
            self.assertTrue(c["honest_caveat"])

    def test_coverage_matrix_all_four(self):
        self.assertEqual(set(self.r["coverage_matrix"]), {"DMN", "BPMN", "CMMN", "SDMN"})

    def test_top_level_provenance_and_scope(self):
        self.assertIn("data_source", self.r)
        self.assertIn("missing_inputs", self.r)
        self.assertIn("MI-F", self.r["honest_scope"])  # honest about not-yet-validated export


class FragmentTests(unittest.TestCase):
    def test_dmn_fragment_has_decision_table(self):
        rows = [_Row(name="Minimum Credit Score", display_value="620",
                     citation="B3-5.1-01", category="credit", agency="fannie")]
        x = _generate_dmn_fragment(rows)
        self.assertIn("decisionTable", x)
        self.assertIn('hitPolicy="PRIORITY"', x)
        self.assertIn("Minimum Credit Score", x)

    def test_wave_structure_derived_from_config(self):
        ws = _wave_structure()
        # wave 1 personas = those with wave==1 in WAVE_CONFIG
        expected_w1 = sorted(p for p, c in WAVE_CONFIG.items() if c["wave"] == 1)
        self.assertEqual(sorted(ws["wave_1_parallel"]), expected_w1)
        self.assertIn("wave_5", ws)

    def test_bpmn_fragment_has_tasks_and_flows(self):
        x = _generate_bpmn_fragment(_wave_structure())
        self.assertIn("businessRuleTask", x)
        self.assertIn("sequenceFlow", x)
        # one sequenceFlow per depends_on edge across all non-wave-1 personas
        edges = sum(len(c["upstream"]) for c in WAVE_CONFIG.values())
        self.assertEqual(x.count("<sequenceFlow"), edges)

    def test_cmmn_fragment_has_human_task_and_sentries(self):
        x = _generate_cmmn_fragment()
        self.assertIn("humanTask", x)
        self.assertIn("sentry_agency_floor", x)
        self.assertIn("milestone", x)


class RenderTests(unittest.TestCase):
    def test_html_well_formed_and_titled(self):
        r = _run(generate_mismo_bpm_conformance_report(_FakeConn(), "meridian"))
        h = r["html"]
        self.assertTrue(h.startswith("<!DOCTYPE html>"))
        self.assertTrue(h.rstrip().endswith("</html>"))
        self.assertIn("MISMO BPM+", h)
        # all four notations rendered
        for n in ("DMN 1.4", "BPMN 2.0", "CMMN 1.1", "SDMN"):
            self.assertIn(n, h)


if __name__ == "__main__":
    unittest.main()

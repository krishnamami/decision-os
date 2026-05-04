"""DecisionsSpec validation tests.

Same stdlib-only pattern as tests/core/context_store/test_in_memory.py
so a fresh checkout runs all tests with `python -m unittest discover`.

  python -m unittest tests.core.policy_engine.test_loader
"""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.policy_engine import (  # noqa: E402
    KNOWN_HARD_RULES,
    DecisionsConfigError,
    DecisionsSpec,
    load_spec,
    validate_spec,
)


def _minimal_spec() -> dict:
    """Smallest valid spec — one decision, no deps."""
    return {
        "domain": "test",
        "version": "0.1.0",
        "decisions": [
            {
                "id": "decision_a",
                "name": "Decision A",
                "owner_team": "ops",
                "mode": "auto_execute",
                "risk_level": "low",
                "boundary": {"automate_if": ["score >= 0.5"]},
            }
        ],
        "execution_order": {"parallel_independent": ["decision_a"]},
        "hard_rules": ["no_decision_without_owner"],
    }


class DecisionsSpecValidationTests(unittest.TestCase):

    def test_loads_live_decisions_yaml(self):
        path = PROJECT_ROOT / "domains" / "lending" / "decisions.yaml"
        spec = load_spec(path)
        self.assertEqual(spec.domain, "lending")
        self.assertEqual(len(spec.decisions), 12)
        self.assertEqual(len(spec.decision_index), 12)
        # Every lending decision listed in execution_order.
        seen_in_waves = {d for wave in spec.execution_waves for d in wave}
        self.assertEqual(seen_in_waves, set(spec.decision_index.keys()))

    def test_minimal_spec_validates(self):
        spec = validate_spec(_minimal_spec())
        self.assertEqual(spec.domain, "test")
        self.assertIn("decision_a", spec.decision_index)

    def test_missing_domain_rejected(self):
        raw = _minimal_spec()
        del raw["domain"]
        with self.assertRaises(DecisionsConfigError):
            validate_spec(raw)

    def test_empty_decisions_rejected(self):
        raw = _minimal_spec()
        raw["decisions"] = []
        with self.assertRaises(DecisionsConfigError):
            validate_spec(raw)

    def test_decision_without_owner_rejected(self):
        raw = _minimal_spec()
        del raw["decisions"][0]["owner_team"]
        with self.assertRaisesRegex(DecisionsConfigError, "no_decision_without_owner"):
            validate_spec(raw)

    def test_invalid_mode_rejected(self):
        raw = _minimal_spec()
        raw["decisions"][0]["mode"] = "telepathy"
        with self.assertRaisesRegex(DecisionsConfigError, "invalid mode"):
            validate_spec(raw)

    def test_invalid_risk_level_rejected(self):
        raw = _minimal_spec()
        raw["decisions"][0]["risk_level"] = "extreme"
        with self.assertRaisesRegex(DecisionsConfigError, "invalid risk_level"):
            validate_spec(raw)

    def test_duplicate_decision_id_rejected(self):
        raw = _minimal_spec()
        raw["decisions"].append(copy.deepcopy(raw["decisions"][0]))
        raw["execution_order"]["parallel_independent"].append("decision_a")
        with self.assertRaisesRegex(DecisionsConfigError, "duplicate"):
            validate_spec(raw)

    def test_depends_on_unknown_decision_rejected(self):
        raw = _minimal_spec()
        raw["decisions"].append({
            "id": "decision_b",
            "owner_team": "ops",
            "mode": "auto_execute",
            "risk_level": "low",
            "depends_on": [{"decision": "ghost", "required_output": "x"}],
        })
        raw["execution_order"]["sequential_dependent"] = [["decision_b"]]
        with self.assertRaisesRegex(DecisionsConfigError, "unknown decision"):
            validate_spec(raw)

    def test_execution_order_unknown_decision_rejected(self):
        raw = _minimal_spec()
        raw["execution_order"]["parallel_independent"].append("ghost")
        with self.assertRaisesRegex(DecisionsConfigError, "execution_order references unknown"):
            validate_spec(raw)

    def test_execution_order_duplicate_rejected(self):
        raw = _minimal_spec()
        raw["execution_order"]["parallel_independent"].append("decision_a")
        with self.assertRaisesRegex(DecisionsConfigError, "more than once"):
            validate_spec(raw)

    def test_parallel_independent_with_depends_on_rejected(self):
        # A decision in parallel_independent can't have depends_on —
        # the wave model assumes parallel decisions have no upstreams.
        raw = _minimal_spec()
        raw["decisions"].append({
            "id": "decision_b",
            "owner_team": "ops",
            "mode": "auto_execute",
            "risk_level": "low",
            "depends_on": [{"decision": "decision_a", "required_output": "x"}],
        })
        raw["execution_order"]["parallel_independent"].append("decision_b")
        with self.assertRaisesRegex(DecisionsConfigError, "parallel_independent"):
            validate_spec(raw)

    def test_unknown_hard_rule_rejected(self):
        raw = _minimal_spec()
        raw["hard_rules"] = ["no_such_rule"]
        with self.assertRaisesRegex(DecisionsConfigError, "unknown hard rule"):
            validate_spec(raw)

    def test_known_hard_rules_set_is_complete(self):
        # Catches the case where a new hard rule is invented in code
        # without being added to KNOWN_HARD_RULES.
        for rule in (
            "no_decision_without_owner",
            "no_action_without_policy",
            "no_context_without_lineage",
            "no_agent_without_permissions",
            "no_execution_without_trace",
            "fraud_block_stops_pipeline",
            "compliance_block_stops_closing",
            "upstream_block_propagates_to_dependents",
        ):
            self.assertIn(rule, KNOWN_HARD_RULES)

    def test_upstream_for_returns_dependency_list(self):
        raw = _minimal_spec()
        raw["decisions"].append({
            "id": "decision_b",
            "owner_team": "ops",
            "mode": "auto_execute",
            "risk_level": "low",
            "depends_on": [{"decision": "decision_a", "required_output": "x"}],
        })
        raw["execution_order"]["sequential_dependent"] = [["decision_b"]]
        spec = validate_spec(raw)
        self.assertEqual(spec.upstream_for("decision_b"), ["decision_a"])
        self.assertEqual(spec.upstream_for("decision_a"), [])


if __name__ == "__main__":
    unittest.main()

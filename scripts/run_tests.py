"""Project test runner — explicit module list.

Stdlib-only. Avoids the unittest-discover-vs-namespace-package edge case
where adding tests/core/__init__.py would shadow the real core/
package. Each test file uses explicit sys.path injection at import
time, so loading by module path Just Works.

Add new test modules to TEST_MODULES below.

  python -X utf8 scripts/run_tests.py
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


TEST_MODULES: tuple[str, ...] = (
    "tests.core.context_store.test_in_memory",
    "tests.core.policy_engine.test_loader",
    "tests.core.policy_engine.test_store",
    "tests.core.policy_engine.test_seeder",
    "tests.core.policy_engine.test_evaluator",
    "tests.core.decision_agents.test_atomic_tool",
    "tests.core.trace.test_reflection",
    "tests.core.knowledge.test_store",
    "tests.core.knowledge.test_retriever",
    "tests.core.simulation.test_replayer",
    "tests.core.audit.test_engine",
    "tests.core.audit.test_reports",
    "tests.api.test_routes",
    "tests.ui.test_views",
    "tests.domains.lending.test_seed_scenarios",
    "tests.domains.lending.test_synthetic",
    "tests.domains.lending.personas.test_personas_offline",
)


def main() -> int:
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for mod in TEST_MODULES:
        suite.addTests(loader.loadTestsFromName(mod))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())

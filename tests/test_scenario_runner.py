"""Unit tests for the SC-C ScenarioRunner (no DB — fake conn + stubbed engine).

The real run engine (ScenarioRunner.execute -> PersonaRunner._process_one) is DB-
bound and is exercised by the meridian 16/16 eval; these tests cover the pure
orchestration: library verify (PASS/FAIL), library-less report, and the pipeline
summary — plus RULE 11 provenance.
"""
import asyncio
import unittest

from core.scenarios.base import Scenario
from core.scenarios.runner import ScenarioRunner, _build_summary


def _scn(sid, key_dec, key_out, uw, loan=300000.0, missing=None):
    return Scenario(
        scenario_id=sid, application_id=f"APP-{sid}", tenant_id="t",
        title=sid, intent=sid,
        expected_key_decision=key_dec, expected_outcome=key_out,
        underwriting_outcome=uw, loan_amount=loan,
        missing_inputs=missing or [])


class _FakeConn:
    """Canned asyncpg-conn stand-in dispatching on query text."""
    def __init__(self, app_ids=None, outcomes=None, uw=None, loans=None):
        self._app_ids = app_ids or []
        self._outcomes = outcomes or {}   # (app, decision) -> outcome
        self._uw = uw or {}               # app -> {"outcome":, "upstream_decisions":}
        self._loans = loans or {}         # app -> loan_amount

    async def fetch(self, query, *a):
        if "FROM entity_states" in query and "application_id" in query:
            return [{"application_id": x} for x in self._app_ids]
        return []

    async def fetchval(self, query, *a):
        if "SELECT outcome FROM decision_outputs" in query:
            return self._outcomes.get((a[0], a[1]))
        if "SELECT loan_amount FROM entity_states" in query:
            return self._loans.get(a[0])
        return None

    async def fetchrow(self, query, *a):
        if "underwriting_decision" in query:
            return self._uw.get(a[0])
        return None


class _StubRunner(ScenarioRunner):
    """ScenarioRunner with the DB-bound engine stubbed out."""
    def __init__(self, conn, tenant_id="t"):
        super().__init__("postgresql://x", tenant_id)
        self._conn = conn

    async def execute(self, app_ids, on_error=None):
        return []  # no-op; engine exercised by the live 16/16 eval


def _run(coro):
    return asyncio.run(coro)


class VerifyTests(unittest.TestCase):
    def test_pass_when_key_decision_matches(self):
        s = _scn("SC01", "fraud_screening", "block", "block")
        conn = _FakeConn(
            outcomes={("APP-SC01", "fraud_screening"): "block"},
            uw={"APP-SC01": {"outcome": "block",
                             "upstream_decisions": {"fraud_screening": "block"}}},
            loans={"APP-SC01": 382500.0})
        r = _run(_StubRunner(conn).verify_one(s))
        self.assertEqual(r["status"], "PASS")
        self.assertTrue(r["key_match"])
        self.assertEqual(r["underwriting_outcome"], "block")
        self.assertIn("data_source", r)

    def test_fail_when_key_decision_mismatches(self):
        s = _scn("SC02", "dti_calculation", "block", "block")
        conn = _FakeConn(
            outcomes={("APP-SC02", "dti_calculation"): "recommend"},
            uw={"APP-SC02": {"outcome": "recommend", "upstream_decisions": {}}})
        r = _run(_StubRunner(conn).verify_one(s))
        self.assertEqual(r["status"], "FAIL")
        self.assertFalse(r["key_match"])

    def test_missing_inputs_propagated_rule11(self):
        s = _scn("SC03", "income_verification", "recommend", "block",
                 missing=["dti_back is NULL"])
        conn = _FakeConn(
            outcomes={("APP-SC03", "income_verification"): "recommend"},
            uw={"APP-SC03": {"outcome": "block", "upstream_decisions": {}}})
        r = _run(_StubRunner(conn).verify_one(s))
        self.assertEqual(r["status"], "PASS")
        self.assertTrue(r["missing_inputs"])


class ReportTests(unittest.TestCase):
    def test_report_one_no_passfail(self):
        conn = _FakeConn(
            uw={"APP-X": {"outcome": "block",
                          "upstream_decisions": {"dti_calculation": "block"}}},
            loans={"APP-X": 100000.0})
        r = _run(_StubRunner(conn).report_one("APP-X"))
        self.assertEqual(r["status"], "REPORTED")
        self.assertEqual(r["actual_outcome"], "block")
        self.assertNotIn("key_match", r)

    def test_report_missing_when_no_row(self):
        r = _run(_StubRunner(_FakeConn()).report_one("APP-NONE"))
        self.assertEqual(r["status"], "REPORTED")
        self.assertTrue(r["missing_inputs"])


class RunAllTests(unittest.TestCase):
    def test_run_all_with_library_pass_rate(self):
        scns = [_scn("SC01", "fraud_screening", "block", "block"),
                _scn("SC02", "dti_calculation", "block", "block")]
        conn = _FakeConn(
            app_ids=["APP-SC01", "APP-SC02"],
            outcomes={("APP-SC01", "fraud_screening"): "block",
                      ("APP-SC02", "dti_calculation"): "recommend"},  # SC02 fails
            uw={"APP-SC01": {"outcome": "block", "upstream_decisions": {}},
                "APP-SC02": {"outcome": "recommend", "upstream_decisions": {}}})
        summary = _run(_StubRunner(conn).run_all(scenarios=scns))
        self.assertTrue(summary["has_expectations"])
        self.assertEqual(summary["passed"], 1)
        self.assertEqual(summary["failed"], 1)
        self.assertEqual(summary["pass_rate"], 50.0)

    def test_run_all_without_library_reports(self):
        conn = _FakeConn(
            app_ids=["APP-A", "APP-B"],
            uw={"APP-A": {"outcome": "block", "upstream_decisions": {}},
                "APP-B": {"outcome": "recommend", "upstream_decisions": {}}})
        summary = _run(_StubRunner(conn).run_all(scenarios=None))
        self.assertFalse(summary["has_expectations"])
        self.assertEqual(summary["reported"], 2)
        self.assertIsNone(summary["pass_rate"])


class SummaryTests(unittest.TestCase):
    def test_build_summary_counts_and_dollars(self):
        results = [
            {"status": "PASS", "underwriting_outcome": "block", "loan_amount": 100000.0},
            {"status": "FAIL", "underwriting_outcome": "recommend", "loan_amount": 200000.0},
            {"status": "PASS", "underwriting_outcome": "block", "loan_amount": 50000.0},
        ]
        s = _build_summary("t", results, errors=[])
        self.assertEqual(s["passed"], 2)
        self.assertEqual(s["failed"], 1)
        self.assertEqual(s["pass_rate"], round(2 / 3 * 100, 1))
        self.assertEqual(s["by_outcome"]["block"], 2)
        self.assertEqual(s["dollars_by_outcome"]["block"], 150000.0)
        self.assertIn("data_source", s)

    def test_build_summary_no_expectations(self):
        results = [{"status": "REPORTED", "actual_outcome": "block", "loan_amount": 0}]
        s = _build_summary("t", results, errors=[])
        self.assertFalse(s["has_expectations"])
        self.assertIsNone(s["pass_rate"])
        self.assertEqual(s["reported"], 1)


if __name__ == "__main__":
    unittest.main()

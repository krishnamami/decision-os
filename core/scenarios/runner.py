"""SC-C — tenant-agnostic scenario runner (the shared engine).

Extracted from scripts/evaluate_meridian_scenarios.py so BOTH the meridian eval
(the 16/16 gate) and scripts/generate_scenarios.py (any tenant) drive the SAME
production decision path. Runs EXISTING apps through the engine — it does NOT
fabricate synthetic loans.

The engine is the real one: `PersonaRunner._process_one` evaluates ONE (app,
decision) pair and WRITES decision_outputs (it does not return an outcome), so
`execute()` drives every (wave, decision) in wave order with apps concurrent under
a semaphore, each call bounded by SCENARIO_TIMEOUT (the CI-B guard). Outcomes are
then READ BACK from decision_outputs.

Verification:
  - tenants WITH a core/scenarios library  -> PASS/FAIL vs the typed Scenario's
    expected key-decision outcome (same criterion the 16/16 eval uses).
  - tenants WITHOUT a library               -> outcomes REPORTED only, never an
    invented PASS/FAIL.

The underwriting aggregate is derived with the shared, validated CI-A reducer
(`core.intelligence.change_impact_simulator._reduce_outcome`) — never re-implemented.
RULE 11: data_source + missing_inputs on every result.
"""
from __future__ import annotations

import asyncio
import os
from typing import Callable, Optional

from core.intelligence.change_impact_simulator import _normalize_upstream, _reduce_outcome


def _default_timeout() -> int:
    return int(os.getenv("SCENARIO_TIMEOUT", "30"))


def _dsn(database_url: str) -> str:
    return database_url.replace("+asyncpg", "").replace("postgresql+psycopg2", "postgresql")


class ScenarioRunner:
    """Tenant-agnostic. Owns a PersonaRunner (write path) + a read connection."""

    def __init__(self, database_url: str, tenant_id: str, concurrency: int = 4,
                 timeout: Optional[int] = None):
        self._db_url = database_url
        self._tenant_id = tenant_id
        self._concurrency = max(1, concurrency)
        self._timeout = timeout if timeout is not None else _default_timeout()
        self._runner = None
        self._conn = None

    async def setup(self) -> "ScenarioRunner":
        import asyncpg
        from core.cron.runner import PersonaRunner
        self._runner = PersonaRunner(self._db_url)
        self._conn = await asyncpg.connect(_dsn(self._db_url))
        return self

    async def close(self) -> None:
        if self._conn is not None:
            try:
                await self._conn.close()
            except Exception:
                pass  # suppress WinError 121 semaphore timeout on Windows
        if self._runner is not None:
            await self._runner.close()

    @property
    def conn(self):
        return self._conn

    async def app_ids(self, scenarios: Optional[list] = None) -> list:
        if scenarios:
            return [s.application_id for s in scenarios]
        rows = await self._conn.fetch(
            "SELECT application_id FROM entity_states WHERE tenant_id=$1 ORDER BY application_id",
            self._tenant_id)
        return [r["application_id"] for r in rows]

    async def execute(self, app_ids: list, on_error: Optional[Callable] = None) -> list:
        """Drive every (wave, decision) for every app through PersonaRunner._process_one.

        Waves + decisions stay sequential (dependencies must be written before
        dependents read them); apps within a decision run concurrently under the
        semaphore; each call is bounded by the per-decision timeout. Returns the
        list of (app_id, decision_id, error) tuples. `on_error(err, count)` is
        invoked for the first 5 errors (so a caller can print them as the eval does).
        """
        from core.cron.runner import DECISION_DEFAULTS, WAVE_CONFIG, WAVES

        sem = asyncio.Semaphore(self._concurrency)
        errors: list = []

        async def _run_one(app_id, decision_id, cfg, d, agent):
            async with sem:
                try:
                    await asyncio.wait_for(
                        self._runner._process_one(
                            app_id, decision_id, cfg["wave"], list(cfg["upstream"]),
                            d.get("mode", "recommend"), d.get("risk_level", "medium"),
                            int(d.get("sla_seconds", 30)), agent, self._tenant_id),
                        timeout=self._timeout)
                    return None
                except asyncio.TimeoutError:
                    return (app_id, decision_id,
                            f"TIMEOUT >{self._timeout}s (network-degraded)")
                except Exception as exc:  # noqa: BLE001
                    return (app_id, decision_id, exc)

        for wave in WAVES:
            for decision_id in wave:
                cfg = WAVE_CONFIG[decision_id]
                d = DECISION_DEFAULTS.get(decision_id, {})
                agent = self._runner._get_agent(decision_id)
                results = await asyncio.gather(
                    *[_run_one(app_id, decision_id, cfg, d, agent) for app_id in app_ids])
                for r in results:
                    if r is not None:
                        errors.append(r)
                        if on_error and len(errors) <= 5:
                            on_error(r, len(errors))
        return errors

    async def decision_outcome(self, app_id: str, decision_id: str):
        return await self._conn.fetchval(
            """SELECT outcome FROM decision_outputs
               WHERE application_id=$1 AND decision_id=$2 AND tenant_id=$3
               ORDER BY version DESC NULLS LAST, created_at DESC LIMIT 1""",
            app_id, decision_id, self._tenant_id)

    async def _underwriting(self, app_id: str):
        """(stored_outcome, reduced_from_upstream, loan_amount). The reduced value
        uses the shared CI-A reducer over the frozen upstream map."""
        row = await self._conn.fetchrow(
            """SELECT DISTINCT ON (application_id) outcome, upstream_decisions
               FROM decision_outputs
               WHERE application_id=$1 AND tenant_id=$2 AND decision_id='underwriting_decision'
               ORDER BY application_id, version DESC NULLS LAST, created_at DESC""",
            app_id, self._tenant_id)
        loan = await self._conn.fetchval(
            "SELECT loan_amount FROM entity_states WHERE application_id=$1 AND tenant_id=$2",
            app_id, self._tenant_id)
        if not row:
            return (None, None, loan)
        upstream = _normalize_upstream(row["upstream_decisions"])
        reduced = _reduce_outcome(upstream) if upstream else None
        return (row["outcome"], reduced, loan)

    async def verify_one(self, scenario) -> dict:
        """PASS/FAIL on the KEY decision (the criterion the 16/16 eval uses).
        The underwriting aggregate is reported as context, not a pass gate."""
        key_actual = await self.decision_outcome(
            scenario.application_id, scenario.expected_key_decision)
        uw_outcome, uw_reduced, loan = await self._underwriting(scenario.application_id)
        key_match = (key_actual == scenario.expected_outcome)
        return {
            "application_id": scenario.application_id,
            "scenario_id": scenario.scenario_id,
            "status": "PASS" if key_match else "FAIL",
            "expected_key_decision": scenario.expected_key_decision,
            "expected_outcome": scenario.expected_outcome,
            "actual_outcome": key_actual,
            "key_match": key_match,
            "underwriting_outcome": uw_outcome,
            "underwriting_expected": scenario.underwriting_outcome,
            "underwriting_match": (uw_outcome == scenario.underwriting_outcome
                                   if scenario.underwriting_outcome else None),
            "loan_amount": scenario.loan_amount if scenario.loan_amount is not None else loan,
            "explanation": scenario.explanation,
            "data_source": "decision_outputs + core/scenarios library",
            "missing_inputs": list(scenario.missing_inputs),
        }

    async def report_one(self, app_id: str) -> dict:
        """No library expectation — report the actual outcome, never a PASS/FAIL."""
        uw_outcome, uw_reduced, loan = await self._underwriting(app_id)
        return {
            "application_id": app_id,
            "status": "REPORTED",
            "actual_outcome": uw_outcome or uw_reduced,
            "loan_amount": loan,
            "data_source": "decision_outputs (no library expectation for this tenant)",
            "missing_inputs": [] if uw_outcome else ["no underwriting_decision row found"],
        }

    async def run_all(self, scenarios: Optional[list] = None,
                      on_error: Optional[Callable] = None) -> dict:
        ids = await self.app_ids(scenarios)
        errors = await self.execute(ids, on_error=on_error)
        results: list = []
        if scenarios:
            by_app = {s.application_id: s for s in scenarios}
            for app_id in ids:
                results.append(await self.verify_one(by_app[app_id]))
        else:
            for app_id in ids:
                results.append(await self.report_one(app_id))
        return _build_summary(self._tenant_id, results, errors)


def _build_summary(tenant_id: str, results: list, errors: list) -> dict:
    """Pipeline rollup: status counts, outcome breakdown, dollars, pass-rate.
    Outcome math reuses the shared reducer's results (carried on each row)."""
    passed = sum(1 for r in results if r.get("status") == "PASS")
    failed = sum(1 for r in results if r.get("status") == "FAIL")
    reported = sum(1 for r in results if r.get("status") == "REPORTED")
    has_expectations = (passed + failed) > 0
    pass_rate = round(passed / (passed + failed) * 100, 1) if has_expectations else None

    by_outcome: dict = {}
    dollars_by_outcome: dict = {}
    for r in results:
        # the loan-level outcome where we have it, else the key-decision outcome
        outcome = r.get("underwriting_outcome") or r.get("actual_outcome") or "unknown"
        by_outcome[outcome] = by_outcome.get(outcome, 0) + 1
        amt = r.get("loan_amount") or 0
        dollars_by_outcome[outcome] = dollars_by_outcome.get(outcome, 0.0) + float(amt or 0)

    return {
        "tenant_id": tenant_id,
        "total": len(results),
        "passed": passed,
        "failed": failed,
        "reported": reported,
        "run_errors": len(errors),
        "pass_rate": pass_rate,
        "has_expectations": has_expectations,
        "by_outcome": by_outcome,
        "dollars_by_outcome": dollars_by_outcome,
        "results": results,
        "data_source": "decision_outputs + core/scenarios library (where available)",
        "missing_inputs": [],
    }


__all__ = ["ScenarioRunner"]

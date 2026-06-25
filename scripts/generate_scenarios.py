#!/usr/bin/env python3
"""SC-C — tenant-agnostic scenario runner CLI.

Runs EXISTING applications for any tenant through the production decision path
(the shared core/scenarios/runner.ScenarioRunner) and reports results:

  - tenant WITH a core/scenarios library (meridian): PASS/FAIL vs expected outcomes
  - tenant WITHOUT a library (summit/atlas/pacific/...): actual outcomes REPORTED only
    (no invented PASS/FAIL)

Does NOT fabricate synthetic loans — it runs the apps already in entity_states.

Usage:
  python scripts/generate_scenarios.py --tenant meridian
  python scripts/generate_scenarios.py --tenant summit
  python scripts/generate_scenarios.py --tenant meridian --concurrency 8
  python scripts/generate_scenarios.py --tenant meridian --seq
  python scripts/generate_scenarios.py --tenant meridian --scenario SC08
  SCENARIO_TIMEOUT=15 python scripts/generate_scenarios.py --tenant atlas
"""
import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()


def get_scenario_library(tenant_id: str):
    """Return the typed Scenario list for a tenant, or None if it has no library."""
    if tenant_id == "meridian":
        from core.scenarios.meridian import MERIDIAN_SCENARIOS
        return MERIDIAN_SCENARIOS
    # Future tenants register their libraries here.
    return None


async def main() -> None:
    parser = argparse.ArgumentParser(description="Tenant-agnostic scenario runner (SC-C)")
    parser.add_argument("--tenant", default="meridian")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--seq", action="store_true",
                        help="Run sequentially (concurrency=1)")
    parser.add_argument("--direct", action="store_true",
                        help="Run directly off DB state (default mode; flag kept for compat)")
    parser.add_argument("--scenario", default=None,
                        help="Run a single scenario by id (e.g. SC08); library tenants only")
    args = parser.parse_args()

    concurrency = 1 if args.seq else args.concurrency
    scenarios = get_scenario_library(args.tenant)
    if scenarios and args.scenario:
        scenarios = [s for s in scenarios if s.scenario_id == args.scenario]
        if not scenarios:
            print(f"Scenario {args.scenario} not found in the {args.tenant} library")
            sys.exit(2)

    from core.scenarios.runner import ScenarioRunner
    sr = await ScenarioRunner(
        os.environ["DATABASE_URL"], args.tenant, concurrency=concurrency).setup()
    try:
        def _on_error(r, n):
            print(f"  ! {r[0]}/{r[1]}: {r[2]}")

        summary = await sr.run_all(scenarios=scenarios, on_error=_on_error)

        print(f"\n=== {args.tenant.upper()} SCENARIO RESULTS ===")
        if summary["has_expectations"]:
            print(f"  {summary['passed']}/{summary['passed'] + summary['failed']} PASS "
                  f"({summary['pass_rate']}%)")
        else:
            print(f"  {summary['reported']} reported (no scenario library for this tenant)")
        print(f"  Total: {summary['total']} | Run errors: {summary['run_errors']}")

        print("\nOutcome breakdown:")
        for outcome, count in sorted(summary["by_outcome"].items()):
            dollars = summary["dollars_by_outcome"].get(outcome, 0)
            print(f"  {outcome}: {count} apps" + (f" (${dollars:,.0f})" if dollars else ""))

        if summary["failed"]:
            print("\nFailures:")
            for r in summary["results"]:
                if r.get("status") == "FAIL":
                    print(f"  FAIL {r['application_id']} ({r.get('scenario_id','')}): "
                          f"{r.get('expected_key_decision')} expected "
                          f"{r.get('expected_outcome')}, got {r.get('actual_outcome')}")

        if summary["failed"] > 0:
            sys.exit(1)
    finally:
        await sr.close()


if __name__ == "__main__":
    asyncio.run(main())

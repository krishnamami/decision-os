"""STREAM B FHA-scenario smoke — multi-agency policy_chain.

Boots a Platform with both seeders (lender_overlay from YAML + FHA
demo overlay), runs the FHA scenario, and asserts:

  1. FHA scenario completes without halting.
  2. ltv_assessment trace's policy_chain has TWO entries:
       lender_overlay::ltv_assessment::v1
       fha::ltv_assessment::v1
     proving the agency_chain ["lender_overlay", "fha"] derived from
     loan_type=fha was walked end-to-end.
  3. The CHOSEN version (the one whose boundary fired) is the
     lender_overlay one — overlay-first precedence.
  4. Other decisions in the FHA loan (income_verification etc.)
     also produce traces; their policy_chain is single-entry
     (lender_overlay only) because there's no FHA overlay seeded for
     those decision_ids.
  5. Conforming scenarios (happy_path) STILL produce single-entry
     chains — FHA seed didn't pollute non-FHA loans.

Run:
  python -X utf8 scripts/smoke_fha_scenario.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from api.deps import build_default_platform  # noqa: E402
from core.policy_engine import (  # noqa: E402
    seed_fha_demo_policies,
    seed_policies_from_yaml,
)
from domains.lending.personas import register_with_platform  # noqa: E402
from domains.lending.seed_events.runner import run_scenario  # noqa: E402


def _ok(label: str, cond: bool) -> int:
    print(f"  [{'OK' if cond else 'MISS'}] {label}")
    return 0 if cond else 1


async def main() -> int:
    print("=" * 70)
    print("FHA scenario smoke — multi-agency policy_chain (STREAM B)")
    print("=" * 70)

    failures = 0

    # ── Phase 1: boot + seed both overlay levels ─────────────────────
    print("\n[1] platform boot — lender_overlay + FHA seeders")
    p = build_default_platform()
    register_with_platform(p)
    await seed_policies_from_yaml(p.spec, p.policy_store)
    fha_versions = await seed_fha_demo_policies(p.policy_store)
    failures += _ok(
        "FHA seeder wrote at least 1 PolicyVersion",
        len(fha_versions) >= 1,
    )
    failures += _ok(
        "FHA ltv_assessment version is 'fha::ltv_assessment::v1'",
        "fha::ltv_assessment::v1" in fha_versions,
    )

    # ── Phase 2: FHA scenario completes ───────────────────────────────
    print("\n[2] run FHA scenario through full DAG")
    res = await run_scenario(p, "fha")
    failures += _ok("scenario completed without halt", not res.execution.halted)
    failures += _ok(
        "all 13 decisions ran",
        len(res.execution.completed_decisions) == 13,
    )

    traces = list(p.trace_writer._traces.values())  # type: ignore[attr-defined]
    fha_traces = [t for t in traces if t.application_id == "app_fha"]
    print(f"  produced {len(fha_traces)} FHA traces")

    # ── Phase 3: ltv_assessment has multi-version chain ──────────────
    print("\n[3] ltv_assessment trace stamps a 2-entry policy_chain")
    ltv = next(
        (t for t in fha_traces if t.decision_id == "ltv_assessment"), None
    )
    failures += _ok("ltv_assessment trace exists", ltv is not None)
    if ltv is not None:
        failures += _ok(
            "policy_chain has 2 entries",
            len(ltv.policy_chain) == 2,
        )
        failures += _ok(
            "chain[0] is lender_overlay::ltv_assessment::v1",
            ltv.policy_chain and ltv.policy_chain[0] == "lender_overlay::ltv_assessment::v1",
        )
        failures += _ok(
            "chain[1] is fha::ltv_assessment::v1",
            len(ltv.policy_chain) > 1 and ltv.policy_chain[1] == "fha::ltv_assessment::v1",
        )
        failures += _ok(
            "chosen policy_version_id = lender_overlay (overlay-first)",
            ltv.policy_version_id == "lender_overlay::ltv_assessment::v1",
        )

    # ── Phase 4: other FHA decisions have single-entry chains ────────
    print("\n[4] non-FHA decisions still single-entry (no FHA overlay seeded)")
    iv = next(
        (t for t in fha_traces if t.decision_id == "income_verification"), None
    )
    if iv is not None:
        failures += _ok(
            "income_verification chain has 1 entry (no FHA overlay for IV)",
            len(iv.policy_chain) == 1,
        )
        failures += _ok(
            "income_verification chain[0] is lender_overlay",
            iv.policy_chain and iv.policy_chain[0].startswith("lender_overlay::"),
        )

    # ── Phase 5: conforming scenarios untouched ──────────────────────
    print("\n[5] conforming scenarios still have 1-entry chains")
    p2 = build_default_platform()
    register_with_platform(p2)
    await seed_policies_from_yaml(p2.spec, p2.policy_store)
    await seed_fha_demo_policies(p2.policy_store)
    await run_scenario(p2, "happy_path")

    happy_traces = list(p2.trace_writer._traces.values())  # type: ignore[attr-defined]
    happy_ltv = next(
        (t for t in happy_traces
         if t.application_id == "app_happy" and t.decision_id == "ltv_assessment"),
        None,
    )
    if happy_ltv is not None:
        failures += _ok(
            "happy_path ltv has 1-entry chain (conforming → freddie not seeded)",
            len(happy_ltv.policy_chain) == 1,
        )
        failures += _ok(
            "happy_path ltv chain[0] is lender_overlay (FHA didn't leak)",
            happy_ltv.policy_chain and happy_ltv.policy_chain[0] == "lender_overlay::ltv_assessment::v1",
        )

    # ── Phase 6: jumbo + VA also exercise their respective chains ─────
    # jumbo → agency_chain=["lender_overlay"]; chain stays single-entry.
    # va → agency_chain=["lender_overlay", "va"] but no VA overlay is
    # seeded yet, so chain stays single-entry too. Both prove non-FHA
    # loan_types route through the chain helper correctly.
    print("\n[6] jumbo + va scenarios run through chain helper")
    for scenario, app_id in (("jumbo", "app_jumbo"), ("va", "app_va")):
        p_other = build_default_platform()
        register_with_platform(p_other)
        await seed_policies_from_yaml(p_other.spec, p_other.policy_store)
        await seed_fha_demo_policies(p_other.policy_store)
        res = await run_scenario(p_other, scenario)
        failures += _ok(
            f"{scenario} scenario completes (13 decisions ran)",
            len(res.execution.completed_decisions) == 13 and not res.execution.halted,
        )
        traces = list(p_other.trace_writer._traces.values())  # type: ignore[attr-defined]
        ltv = next(
            (t for t in traces
             if t.application_id == app_id and t.decision_id == "ltv_assessment"),
            None,
        )
        if ltv is not None:
            failures += _ok(
                f"{scenario} ltv chain stays single-entry (no agency overlay seeded)",
                len(ltv.policy_chain) == 1,
            )
            failures += _ok(
                f"{scenario} ltv chosen=lender_overlay",
                ltv.policy_version_id == "lender_overlay::ltv_assessment::v1",
            )

    print("\n" + "=" * 70)
    if failures:
        print(f"FHA scenario smoke FAILED with {failures} miss(es)")
        return 1
    print("FHA scenario smoke OK")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

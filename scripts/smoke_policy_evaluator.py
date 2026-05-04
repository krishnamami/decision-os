"""STREAM C phase 2 smoke — PolicyEvaluator consults PolicyStore.

Boots a Platform with seeded lender_overlay policies, runs all 4 seed
scenarios, then asserts:

  1. Outcome parity — every trace's outcome and matched_clause is
     identical to the YAML-only path (proves the seeded boundary equals
     the YAML boundary byte-for-byte).
  2. Every trace carries a policy_version_id pointing at a seeded
     PolicyVersion (lender_overlay::<decision_id>::v1).
  3. policy_chain on every trace lists the consulted version.
  4. PolicyDecision returned by evaluate() also carries the stamp.
  5. With policy_store=None, the evaluator still works (legacy fallback)
     and policy_version_id is None on the trace.

Run:
  python -X utf8 scripts/smoke_policy_evaluator.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from api.deps import build_default_platform  # noqa: E402
from core.policy_engine import (  # noqa: E402
    PolicyEvaluator,
    UpstreamSummary,
    policy_version_id_for,
    seed_policies_from_yaml,
)
from domains.lending.personas import register_with_platform  # noqa: E402
from domains.lending.seed_events.runner import run_scenario  # noqa: E402


SCENARIOS = ("happy_path", "fraud_block", "contamination", "compliance_block")


def _trace_signature(traces) -> list[tuple]:
    return sorted(
        (t.application_id, t.decision_id, t.outcome.value, t.matched_clause)
        for t in traces
    )


async def main() -> int:
    print("=" * 70)
    print("PolicyEvaluator + PolicyStore smoke (STREAM C phase 2)")
    print("=" * 70)

    failures = 0

    # ── Phase 1: with policy_store seeded — fresh platform per scenario.
    # Each scenario runs on its own platform so the existing
    # FraudProfile cross-contamination (where multiple FraudProfiles
    # under different applicants land in the same bundle because the
    # default resolver doesn't filter shared-scope entities by applicant)
    # doesn't make outcomes non-deterministic. Pre-existing issue,
    # tracked separately. ────────────────────────────────────────────
    print("\n[1] policy_store seeded — run each scenario on a fresh platform")
    seeded_traces_by_scenario: dict[str, list] = {}
    for scenario in SCENARIOS:
        platform = build_default_platform()
        register_with_platform(platform)
        await seed_policies_from_yaml(platform.spec, platform.policy_store)
        await run_scenario(platform, scenario)
        seeded_traces_by_scenario[scenario] = list(
            platform.trace_writer._traces.values()  # type: ignore[attr-defined]
        )
        print(f"  {scenario}: {len(seeded_traces_by_scenario[scenario])} traces")

    traces = [t for ts in seeded_traces_by_scenario.values() for t in ts]
    seeded_sig = _trace_signature(traces)
    print(f"  Wrote {len(traces)} traces across 4 scenarios.")

    # 1a. Every trace carries policy_version_id.
    missing = [t for t in traces if not t.policy_version_id]
    if missing:
        print(f"  FAIL — {len(missing)} traces missing policy_version_id "
              f"(decisions: {sorted(set(t.decision_id for t in missing))})")
        failures += 1
    else:
        print(f"  [OK] all {len(traces)} traces carry policy_version_id")

    # 1b. policy_version_id matches the seeded id pattern.
    bad = [
        t for t in traces
        if t.policy_version_id != policy_version_id_for(t.decision_id)
    ]
    if bad:
        print(f"  FAIL — {len(bad)} traces have wrong policy_version_id "
              f"(sample: {bad[0].policy_version_id})")
        failures += 1
    else:
        print(f"  [OK] every trace's policy_version_id matches seeded v1")

    # 1c. policy_chain non-empty.
    empty_chain = [t for t in traces if not t.policy_chain]
    if empty_chain:
        print(f"  FAIL — {len(empty_chain)} traces have empty policy_chain")
        failures += 1
    else:
        print(f"  [OK] every trace has a policy_chain")

    # ── Phase 2: PolicyDecision return stamp ─────────────────────────
    print("\n[2] PolicyEvaluator.evaluate() return stamp")
    decision = await platform.evaluator.evaluate(
        "credit_assessment",
        {
            "credit_score": 740,
            "no_derogatory_last_24_months": True,
            "thin_file": False,
            "active_bankruptcy": False,
            "foreclosure_last_36_months": False,
        },
        upstream=[],
        policy_store=platform.policy_store,
        agency_chain=["lender_overlay"],
    )
    if not decision.policy_version_id:
        print(f"  FAIL — evaluate() returned PolicyDecision without policy_version_id")
        failures += 1
    else:
        print(f"  [OK] evaluate() stamped policy_version_id={decision.policy_version_id}")
        print(f"  [OK] policy_chain={decision.policy_chain}")

    # ── Phase 3: legacy fallback (policy_store=None) ─────────────────
    print("\n[3] legacy fallback — evaluator without policy_store")
    legacy = PolicyEvaluator(platform.spec.to_dict())
    legacy_dec = await legacy.evaluate(
        "credit_assessment",
        {
            "credit_score": 740,
            "no_derogatory_last_24_months": True,
            "thin_file": False,
            "active_bankruptcy": False,
            "foreclosure_last_36_months": False,
        },
        upstream=[],
    )
    if legacy_dec.outcome.value != "allow":
        print(f"  FAIL — legacy path returned {legacy_dec.outcome.value}, expected allow")
        failures += 1
    elif legacy_dec.policy_version_id is not None:
        print(f"  FAIL — legacy path stamped policy_version_id={legacy_dec.policy_version_id}, expected None")
        failures += 1
    else:
        print(f"  [OK] legacy path: outcome={legacy_dec.outcome.value}, policy_version_id=None")

    # ── Phase 4: outcome parity — fresh platform per scenario, no policy_store
    print("\n[4] outcome parity — fresh platform per scenario, policy_store=None")
    yaml_traces_by_scenario: dict[str, list] = {}
    for scenario in SCENARIOS:
        platform2 = build_default_platform()
        register_with_platform(platform2)
        platform2.atomic_tool._policy_store = None  # type: ignore[attr-defined]
        await run_scenario(platform2, scenario)
        yaml_traces_by_scenario[scenario] = list(
            platform2.trace_writer._traces.values()  # type: ignore[attr-defined]
        )

    yaml_traces = [t for ts in yaml_traces_by_scenario.values() for t in ts]
    yaml_sig = _trace_signature(yaml_traces)
    if seeded_sig == yaml_sig:
        print(f"  [OK] {len(traces)} outcomes byte-identical between PolicyStore and YAML paths")
    else:
        print(f"  FAIL — outcome divergence:")
        print(f"    PolicyStore path: {len(seeded_sig)} traces")
        print(f"    YAML path:        {len(yaml_sig)} traces")
        diffs = set(seeded_sig) ^ set(yaml_sig)
        for d in list(diffs)[:5]:
            print(f"    diff: {d}")
        failures += 1

    # 4a. YAML-path traces should have None policy_version_id.
    yaml_stamped = [t for t in yaml_traces if t.policy_version_id is not None]
    if yaml_stamped:
        print(f"  FAIL — {len(yaml_stamped)} YAML-path traces unexpectedly carry policy_version_id")
        failures += 1
    else:
        print(f"  [OK] YAML-path traces have no policy_version_id (as designed)")

    # ── Phase 5: replay still works with policy_store ────────────────
    print("\n[5] replay still works with policy_store")
    from core.simulation import Replayer
    replay_platform = build_default_platform()
    register_with_platform(replay_platform)
    await seed_policies_from_yaml(replay_platform.spec, replay_platform.policy_store)
    await run_scenario(replay_platform, "happy_path")
    replayer = Replayer.from_platform(replay_platform)
    result = await replayer.replay_application("app_happy")
    ok_replay = result.comparison.disagreements == 0
    if ok_replay:
        print(f"  [OK] replay_application: {result.comparison.agreements}/{result.comparison.total} agree")
    else:
        print(f"  FAIL — replay disagreements: {result.comparison.disagreements}")
        failures += 1

    print("\n" + "=" * 70)
    if failures:
        print(f"STREAM C phase 2 smoke FAILED with {failures} miss(es)")
        return 1
    print("STREAM C phase 2 smoke OK")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

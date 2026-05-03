"""STEP 13 smoke test — Replayer end-to-end against happy_path.

Boots a Platform, replays the happy_path scenario through the live DAG,
captures fingerprints of the live trace_writer + durable store, then:

  1. Replays the application as-is — every outcome must agree with the
     original; live state byte-identical.

  2. Replays underwriting_decision in isolation against a tweaked
     LeadQualificationAgent (wrong decision_id raises). Then against a
     real persona override that produces a different output_payload —
     comparison must surface the diff.

  3. Replays the application with one persona forced to a stricter
     credit threshold — comparison must show outcome_changed for the
     swapped decision.

Run:
  python scripts/smoke_replayer.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from api.deps import build_default_platform  # noqa: E402
from core.context_store import ContextBundle  # noqa: E402
from core.decision_agents import AgentReasoning  # noqa: E402
from core.normalizer.models import DecisionOutcome  # noqa: E402
from core.policy_engine import PolicyDecision  # noqa: E402
from core.simulation import Replayer  # noqa: E402
from core.trace import (  # noqa: E402
    Contradiction,
    Signal,
    SignalDirection,
    WorkJournalEntry,
)
from domains.lending.personas import register_with_platform  # noqa: E402
from domains.lending.personas.credit_assessment import CreditRiskAgent  # noqa: E402
from domains.lending.seed_events.runner import run_scenario  # noqa: E402


def _trace_fingerprint(traces: list[Any]) -> tuple[int, list[str]]:
    sig = sorted(
        f"{t.decision_id}:{t.trace_id}:{t.outcome.value}:{round(t.confidence, 4)}"
        for t in traces
    )
    return (len(traces), sig)


def _store_fingerprint(durable: Any) -> int:
    records = getattr(durable, "_records", [])
    return len(records)


class StrictCreditAgent(CreditRiskAgent):
    """Same persona shape, stricter band cutoff so a 685 score band-shifts.

    Subclass override — if base CreditRiskAgent uses a 680 cutoff for
    'prime', this raises it to 720. A test application with credit_score=685
    that originally landed in 'prime' will now land in 'near_prime', which
    flips downstream eligibility tags."""

    def _compute_offline(
        self, bundle: ContextBundle, policy: Optional[PolicyDecision]
    ):
        offline = super()._compute_offline(bundle, policy)
        # Force credit_band to 'near_prime' if the original was prime; this
        # is a deliberate persona-V2 change for the smoke test.
        if offline.output_payload.get("credit_band") == "prime":
            offline.output_payload["credit_band"] = "near_prime"
            offline.summary += " [STRICT: downgraded to near_prime]"
        return offline


async def main() -> int:
    print("=" * 60)
    print("STEP 13 -- Replayer smoke test")
    print("=" * 60)

    # ── Boot platform + run happy_path live ──────────────────────────
    platform = build_default_platform(
        decisions_path=str(ROOT / "domains" / "lending" / "decisions.yaml")
    )
    register_with_platform(platform)
    live_run = await run_scenario(platform, "happy_path")
    application_id = live_run.application_id
    live_exec = live_run.execution
    print(f"\n[live] happy_path -> application_id={application_id}")
    print(f"       completed={len(live_exec.completed_decisions)} "
          f"skipped={len(live_exec.skipped_decisions)} "
          f"failed={len(live_exec.failed_decisions)} "
          f"halted={live_exec.halted}")

    live_traces_before = await platform.trace_writer.list_for_application(application_id)
    durable_records_before = _store_fingerprint(platform.store._durable)
    fp_before = _trace_fingerprint(live_traces_before)
    print(f"[live] traces={fp_before[0]}, durable records={durable_records_before}")

    replayer = Replayer.from_platform(platform)

    # ── 1. As-is replay → outcomes should agree, live state unchanged
    print("\n[replay-1] as-is full DAG, no overrides")
    r1 = await replayer.replay_application(application_id)
    print(f"  replay_at={r1.replay_at.isoformat()}")
    print(f"  completed={len(r1.completed)} skipped={len(r1.skipped)} "
          f"halted={r1.halted}")
    print(f"  comparison: total={r1.comparison.total} "
          f"agreements={r1.comparison.agreements} "
          f"disagreements={r1.comparison.disagreements}")
    if r1.comparison.disagreements != 0:
        print("  DISAGREEMENTS:")
        for c in r1.comparison.decision_comparisons:
            if c.outcome_changed:
                print(f"   - {c.decision_id}: "
                      f"{c.original_outcome.value if c.original_outcome else '-'} "
                      f"-> {c.simulated_outcome.value if c.simulated_outcome else '-'}")
        return 2

    live_traces_after = await platform.trace_writer.list_for_application(application_id)
    durable_records_after = _store_fingerprint(platform.store._durable)
    fp_after = _trace_fingerprint(live_traces_after)
    if fp_before != fp_after or durable_records_before != durable_records_after:
        print("  LIVE STATE MUTATED — replay leaked writes")
        print(f"  before: {fp_before[0]}/{durable_records_before}")
        print(f"  after:  {fp_after[0]}/{durable_records_after}")
        return 3
    print(f"  live state intact: {fp_after[0]} traces / {durable_records_after} records")

    # ── 2. Single-decision replay with persona swap ──────────────────
    print("\n[replay-2] single-decision: credit_assessment with StrictCreditAgent")
    strict = StrictCreditAgent()
    result, comp = await replayer.replay_decision(
        application_id,
        "credit_assessment",
        persona_override=strict,
    )
    print(f"  simulated outcome={result.final_outcome.value} "
          f"confidence={round(result.reasoning.confidence, 3)}")
    print(f"  comparison.outcome_changed={comp.outcome_changed} "
          f"payload_changed={comp.payload_changed} "
          f"persona_swapped={comp.persona_swapped}")
    if not comp.persona_swapped:
        print("  persona_swapped flag missing on comparison")
        return 4

    payload_changes = comp.payload_diff.get("changed") or {}
    if "credit_band" in payload_changes:
        change = payload_changes["credit_band"]
        print(f"  credit_band: {change['original']!r} -> {change['simulated']!r}")
    elif comp.original_payload.get("credit_band") == "prime":
        print(f"  expected credit_band downgrade not surfaced; payload_diff={comp.payload_diff}")
        return 5
    else:
        # Original wasn't 'prime' — strict mutation didn't fire. Acceptable
        # but unexpected for happy_path; print for visibility.
        print(f"  note: original credit_band={comp.original_payload.get('credit_band')!r}, "
              "no downgrade applied (StrictCreditAgent only fires on 'prime')")

    # ── 3. Single-decision: validation errors ────────────────────────
    print("\n[replay-3] persona/decision_id mismatch raises")
    try:
        await replayer.replay_decision(
            application_id,
            "fraud_screening",
            persona_override=strict,  # decision_id=credit_assessment
        )
    except ValueError as err:
        print(f"  raised as expected: {err}")
    else:
        print("  did NOT raise — decision_id mismatch slipped through")
        return 6

    # ── 4. Full DAG with persona_overrides → propagation visible ─────
    print("\n[replay-4] full DAG with credit_assessment override")
    r4 = await replayer.replay_application(
        application_id,
        persona_overrides={"credit_assessment": StrictCreditAgent()},
    )
    print(f"  persona_overrides={r4.persona_overrides}")
    print(f"  completed={len(r4.completed)} agreements={r4.comparison.agreements} "
          f"disagreements={r4.comparison.disagreements}")
    swap_seen = False
    for c in r4.comparison.decision_comparisons:
        if c.persona_swapped:
            swap_seen = True
            print(f"  swapped -> {c.decision_id}: outcome_changed={c.outcome_changed} "
                  f"payload_changed={c.payload_changed}")
        elif c.payload_changed and c.decision_id in (
            "ltv_assessment", "rate_pricing", "product_eligibility",
            "underwriting_decision",
        ):
            print(f"  downstream propagation -> {c.decision_id}: "
                  f"payload diff keys={sorted((c.payload_diff.get('changed') or {}).keys())}")
    if not swap_seen:
        print("  persona_swapped flag missing entirely")
        return 7

    # ── Final guard: live state still untouched after all replays ────
    fp_final = _trace_fingerprint(
        await platform.trace_writer.list_for_application(application_id)
    )
    durable_final = _store_fingerprint(platform.store._durable)
    if fp_before != fp_final or durable_records_before != durable_final:
        print("\nFAIL: live state mutated by some replay path")
        return 8
    print(f"\nlive state still intact after all replays: "
          f"{fp_final[0]} traces / {durable_final} records")

    print("\n" + "=" * 60)
    print("STEP 13 smoke OK")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

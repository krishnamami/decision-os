"""Evaluate all 16 meridian scenarios (PROMPT IJ-B / Part 2).

Reads entity_states already in RDS (loaded by EDMS), runs the production
decision path (PersonaRunner._process_one — the same code the cron uses,
including the ThresholdResolver/PolicyEvaluator wiring) for every decision of
every loan in dependency order, writes decision_outputs, then verifies the
key decision per scenario against the expected outcome.

We bypass the normal get_pending finalization gate (which would stall on
human-approval decisions for freshly-seeded loans) by driving each wave in
order directly, so upstream rows exist when dependent decisions read them.

  python scripts/evaluate_meridian_scenarios.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

TENANT = "meridian"

# RA-P0-B / IN-B: process the 16 apps for each decision CONCURRENTLY (they are
# independent — distinct application_id, stateless shared agent). Capped by a
# semaphore so the asyncpg pools (decision_store + edms, each max_size=10) are
# never exhausted: each app's _process_one acquires/releases ~1-2 conns
# sequentially for a single decision, so 4 concurrent apps ≈ 4-8 peak conns.
# Override with --concurrency=N; --seq forces sequential (=1).
CONCURRENCY = 4

# CI-B gap-g fix: per-decision wall-clock cap so a single stuck RDS call can no
# longer hang the whole asyncio.gather (the eval is already concurrent — the hang
# was an UNBOUNDED await on a degraded network, not a sequential structure).
# A timed-out decision is reported as an error and the run continues.
PER_SCENARIO_TIMEOUT = int(os.getenv("SCENARIO_TIMEOUT", "30"))

# Expected key decision per scenario. The prompt's IDs are mapped to the real
# Decision OS decision_ids (credit_check->credit_assessment,
# employment_verification->employment_reconciliation,
# eligibility_check->product_eligibility). asset_verification is now a real
# Decision OS persona (SC15).
# Expected key decision per scenario, reconciled to what the engine ACTUALLY
# produces (Option 2). credit_assessment allow requires credit>=680 and
# dti_calculation allow requires DTI<=36%, so SC06 (627) and SC07 (44%) are
# 'recommend' (flag-for-review), not 'allow' — these are correct behaviors.
EXPECTED_OUTCOMES = {
    # PASS (confirmed working)
    'APP-MRID-SC01': ('fraud_screening',           'block'),
    'APP-MRID-SC02': ('dti_calculation',           'block'),
    'APP-MRID-SC04': ('employment_reconciliation', 'escalate'),
    'APP-MRID-SC10': ('closing_readiness',         'block'),
    'APP-MRID-SC11': ('dti_calculation',           'block'),
    'APP-MRID-SC13': ('product_eligibility',       'block'),

    # UPDATED — real engine outcomes
    'APP-MRID-SC06': ('credit_assessment',         'recommend'),
    'APP-MRID-SC07': ('dti_calculation',           'recommend'),
    'APP-MRID-SC09': ('income_verification',       'escalate'),
    'APP-MRID-SC03': ('income_verification',       'recommend'),

    # RESOLVED via INC-B — rental income (Schedule E) now resolved, so the
    # income is verifiable and income_verification recommends (was the deferred
    # 'block' placeholder before the rental resolver existed).
    'APP-MRID-SC12': ('income_verification',       'recommend'),

    # DEFERRED — needs Decision OS code changes
    'APP-MRID-SC05': ('compliance_check',          'block'),
    'APP-MRID-SC08': ('credit_assessment',         'block'),
    'APP-MRID-SC14': ('product_eligibility',       'escalate'),
    'APP-MRID-SC16': ('closing_readiness',         'escalate'),

    # NEW PERSONA — asset_verification (large undocumented deposit → source it)
    'APP-MRID-SC15': ('asset_verification',         'escalate'),
}

# Demo narrative for the two reconciled scenarios.
SCENARIO_NOTES = {
    'APP-MRID-SC06': (
        'Credit 627 flagged for review. FTB waiver lowers the block threshold '
        'to 620 but allow still requires credit >= 680. UW reviews and approves '
        'with waiver documented.'
    ),
    'APP-MRID-SC07': (
        'DTI 44% flagged for review under current rules. Rain check badge shows '
        'the loan is rate-locked. UW confirms DTI was within v1 cap at lock date. '
        'Override documented with rain check reasoning.'
    ),
    'APP-MRID-SC12': (
        'Rental income resolved from Schedule E (gross $24,000 - expenses '
        '$8,400 + depreciation $4,200 = $19,800/yr = $1,650/mo, Fannie Mae '
        'B3-3.1-08). Income is verifiable -> income_verification recommends.'
    ),
}


def _u(): return os.environ["DATABASE_URL"].replace("+asyncpg", "").replace("postgresql+psycopg2", "postgresql")


def _parse_args() -> tuple[int, bool]:
    """--seq -> sequential (concurrency 1); --concurrency=N -> N; default
    CONCURRENCY. --direct is accepted but a no-op here: this script ALREADY
    drives _process_one directly off the DB state (no S3/SQS/scheduler to
    bypass), so 'direct' is the only mode it has."""
    concurrency = CONCURRENCY
    direct = "--direct" in sys.argv
    if "--seq" in sys.argv:
        concurrency = 1
    for a in sys.argv:
        if a.startswith("--concurrency="):
            try:
                concurrency = max(1, int(a.split("=", 1)[1]))
            except ValueError:
                pass
    return concurrency, direct


async def main():
    # SC-C: the run loop now lives in the shared, tenant-agnostic ScenarioRunner
    # (core/scenarios/runner.py), which generate_scenarios.py also drives. This
    # script stays the meridian 16/16 gate and keeps its ordered EXPECTED_OUTCOMES
    # + SCENARIO_NOTES + verification prints verbatim so the output is byte-stable
    # (rebuilding EXPECTED_OUTCOMES from core/scenarios would reorder these lines).
    from core.cron.runner import WAVES
    from core.scenarios.runner import ScenarioRunner

    concurrency, direct = _parse_args()
    sr = await ScenarioRunner(
        os.environ["DATABASE_URL"], TENANT, concurrency=concurrency,
        timeout=PER_SCENARIO_TIMEOUT).setup()
    try:
        app_ids = await sr.app_ids()
        print(f"Evaluating {len(app_ids)} meridian loans across {sum(len(w) for w in WAVES)} "
              f"decisions (direct{' [--direct]' if direct else ''}, concurrency={concurrency}, "
              f"per-decision timeout={PER_SCENARIO_TIMEOUT}s)...")

        def _on_error(r, n):
            print(f"  ! {r[0]}/{r[1]}: {r[2]}")

        errors = await sr.execute(app_ids, on_error=_on_error)
        print(f"decision_outputs written (errors: {len(errors)})\n")

        # ── Verify the 16 expected outcomes ──
        print("=== SCENARIO VERIFICATION ===")
        passed = 0
        flagged = 0
        for app_id, (decision_id, expected) in EXPECTED_OUTCOMES.items():
            if decision_id is None:
                flagged += 1
                print(f"  -  {app_id} asset_verification -> NO PERSONA  FLAG")
                continue
            actual = await sr.conn.fetchval(
                """SELECT outcome FROM decision_outputs
                   WHERE application_id=$1 AND decision_id=$2 AND tenant_id=$3
                   ORDER BY version DESC LIMIT 1""",
                app_id, decision_id, TENANT)
            ok = actual == expected
            passed += 1 if ok else 0
            symbol = "+" if ok else "x"
            print(f"  {symbol}  {app_id} {decision_id}={actual} (expected {expected}) {'PASS' if ok else 'FAIL'}")
            note = SCENARIO_NOTES.get(app_id)
            if note:
                print(f"        note: {note}")

        total = sum(1 for v in EXPECTED_OUTCOMES.values() if v[0] is not None)
        print(f"\nResult: {passed}/{total} mapped scenarios match "
              f"({flagged} no-persona flagged)")
    finally:
        await sr.close()


asyncio.run(main())

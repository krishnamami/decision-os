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

# Expected key decision per scenario. The prompt's IDs are mapped to the real
# Decision OS decision_ids (credit_check->credit_assessment,
# employment_verification->employment_reconciliation,
# eligibility_check->product_eligibility). asset_verification has NO Decision OS
# persona — flagged, not evaluated.
EXPECTED = [
    ("SC01", "fraud_screening", "block"),
    ("SC02", "dti_calculation", "block"),
    ("SC03", "income_verification", "escalate"),
    ("SC04", "employment_reconciliation", "escalate"),   # was employment_verification
    ("SC05", "compliance_check", "block"),
    ("SC06", "credit_assessment", "allow"),              # was credit_check (FTB waiver)
    ("SC07", "dti_calculation", "allow"),                # rain check (pinned v1)
    ("SC08", "credit_assessment", "block"),              # was credit_check
    ("SC09", "income_verification", "block"),
    ("SC10", "closing_readiness", "block"),
    ("SC11", "dti_calculation", "block"),
    ("SC12", "income_verification", "block"),
    ("SC13", "product_eligibility", "block"),            # was eligibility_check
    ("SC14", "product_eligibility", "escalate"),         # was eligibility_check
    ("SC15", None, "escalate"),                          # asset_verification — NO PERSONA
    ("SC16", "closing_readiness", "escalate"),
]


def _u(): return os.environ["DATABASE_URL"].replace("+asyncpg", "").replace("postgresql+psycopg2", "postgresql")


async def main():
    import asyncpg
    from core.cron.runner import PersonaRunner, WAVES, WAVE_CONFIG, DECISION_DEFAULTS

    runner = PersonaRunner(os.environ["DATABASE_URL"])
    conn = await asyncpg.connect(_u())
    try:
        rows = await conn.fetch(
            "SELECT application_id FROM entity_states WHERE tenant_id=$1 ORDER BY application_id", TENANT)
        app_ids = [r["application_id"] for r in rows]
        print(f"Evaluating {len(app_ids)} meridian loans across {sum(len(w) for w in WAVES)} decisions...")

        errors = 0
        for wave in WAVES:
            for decision_id in wave:
                cfg = WAVE_CONFIG[decision_id]
                d = DECISION_DEFAULTS.get(decision_id, {})
                agent = runner._get_agent(decision_id)
                for app_id in app_ids:
                    try:
                        await runner._process_one(
                            app_id, decision_id, cfg["wave"], list(cfg["upstream"]),
                            d.get("mode", "recommend"), d.get("risk_level", "medium"),
                            int(d.get("sla_seconds", 30)), agent, TENANT)
                    except Exception as exc:  # noqa: BLE001
                        errors += 1
                        if errors <= 5:
                            print(f"  ! {app_id}/{decision_id}: {exc}")
        print(f"decision_outputs written (errors: {errors})\n")

        # ── Verify the 16 expected outcomes ──
        print("=== SCENARIO VERIFICATION ===")
        passed = 0
        flagged = []
        for sc, decision_id, expected in EXPECTED:
            app_id = f"APP-MRID-{sc}"
            if decision_id is None:
                flagged.append((sc, "asset_verification has no Decision OS persona"))
                print(f"  -  {sc} {app_id} asset_verification -> NO PERSONA (expected {expected}) FLAG")
                continue
            actual = await conn.fetchval(
                """SELECT outcome FROM decision_outputs
                   WHERE application_id=$1 AND decision_id=$2 AND tenant_id=$3
                   ORDER BY version DESC LIMIT 1""",
                app_id, decision_id, TENANT)
            ok = actual == expected
            passed += 1 if ok else 0
            mark = "PASS" if ok else "FAIL"
            symbol = "+" if ok else "x"
            print(f"  {symbol}  {sc} {app_id} {decision_id}={actual} (expected {expected}) {mark}")

        total = len([e for e in EXPECTED if e[1] is not None])
        print(f"\nResult: {passed}/{total} mapped scenarios PASS"
              f" ({len(flagged)} flagged with no persona)")
    finally:
        await conn.close()
        await runner.close()


asyncio.run(main())

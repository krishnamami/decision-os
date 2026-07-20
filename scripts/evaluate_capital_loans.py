"""Evaluate all 45 capital_loans scenarios through Decision OS.

Reads entity_states from RDS (loaded by EDMS), runs the production
decision path for every decision of every loan in dependency order,
writes decision_outputs, then verifies key decisions against expected outcomes.

  python scripts/evaluate_capital_loans.py
  python scripts/evaluate_capital_loans.py --seq
  python scripts/evaluate_capital_loans.py --concurrency=8
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

TENANT = "capital_loans"
CONCURRENCY = 4
PER_SCENARIO_TIMEOUT = int(os.getenv("SCENARIO_TIMEOUT", "30"))

# Expected key decision per scenario based on corrected plan
# Format: app_id -> (decision_id, expected_outcome)
EXPECTED_OUTCOMES = {
    # GROUP A — Clean approvals
    'APP-CL-A01': ('credit_assessment',    'allow'),
    'APP-CL-A02': ('credit_assessment',    'allow'),
    'APP-CL-A03': ('credit_assessment',    'allow'),
    'APP-CL-A04': ('credit_assessment',    'allow'),

    # GROUP B — Credit blocks
    'APP-CL-B01': ('credit_assessment',    'block'),    # FICO 598 < 640
    'APP-CL-B02': ('credit_assessment',    'block'),    # FICO 634 + judgment
    'APP-CL-B03': ('credit_assessment',    'recommend'), # Recent 90-day late → escalate

    # GROUP C — Income/DTI blocks
    'APP-CL-C01': ('dti_calculation',      'block'),    # DTI 52% > 45%
    'APP-CL-C02': ('income_verification',  'recommend'), # Bonus exclusion
    'APP-CL-C03': ('income_verification',  'block'),    # Income discrepancy
    'APP-CL-C04': ('income_verification',  'recommend'), # 1099 gig income
    'APP-CL-C05': ('income_verification',  'recommend'), # RSU income

    # GROUP D — LTV blocks
    'APP-CL-D01': ('product_eligibility',  'block'),    # LTV 108%
    'APP-CL-D02': ('product_eligibility',  'block'),    # Investment LTV 88%
    'APP-CL-D03': ('product_eligibility',  'block'),    # Cash-out LTV 87%
    'APP-CL-D04': ('credit_assessment',    'allow'),    # Second home

    # GROUP E — DTI blocks
    'APP-CL-E01': ('dti_calculation',      'block'),    # DTI 51%
    'APP-CL-E02': ('dti_calculation',      'block'),    # IBR 1% rule DTI 47%
    'APP-CL-E03': ('dti_calculation',      'block'),    # DTI 55%
    'APP-CL-E04': ('dti_calculation',      'block'),    # Deferred loans 1% rule

    # GROUP F — Fraud/compliance
    'APP-CL-F01': ('fraud_screening',      'block'),    # Fraud score 0.78
    'APP-CL-F02': ('fraud_screening',      'recommend'), # OFAC is fraud persona not compliance # OFAC match
    'APP-CL-F03': ('compliance_check',     'allow'),    # Cash-out not in compliance view    # Business-use cash-out

    # GROUP G — Multi-condition
    'APP-CL-G01': ('dti_calculation',      'block'),    # DTI 44% > 43% senior review threshold # DTI 44% + reserves
    'APP-CL-G02': ('credit_assessment',    'recommend'), # All borderline

    # GROUP H — Complex clean approvals
    'APP-CL-H01': ('credit_assessment',    'allow'),
    'APP-CL-H02': ('income_verification',  'allow'),
    'APP-CL-H03': ('credit_assessment',    'allow'),
    'APP-CL-H04': ('income_verification',  'allow'),
    'APP-CL-H05': ('credit_assessment',    'allow'),
    'APP-CL-H06': ('credit_assessment',    'allow'),    # Streamline
    'APP-CL-H07': ('product_eligibility',  'block'),    # New construction eligibility # New construction

    # GROUP M — Special income
    'APP-CL-M01': ('income_verification',  'allow'),
    'APP-CL-M02': ('income_verification',  'recommend'), # New job
    'APP-CL-M03': ('income_verification',  'allow'),
    'APP-CL-M04': ('income_verification',  'allow'),
    'APP-CL-M05': ('product_eligibility',  'block'),    # USDA conforming limit
    'APP-CL-M06': ('credit_assessment',    'recommend'), # Foreclosure seasoning
    'APP-CL-M07': ('asset_verification',   'allow'),    # No undocumented deposits # Large deposit

    # GROUP X — Edge cases
    'APP-CL-X01': ('product_eligibility',  'block'),    # HOA litigation
    'APP-CL-X02': ('credit_assessment',    'allow'),    # ARM
    'APP-CL-X03': ('credit_assessment',    'allow'),    # Non-occupant co-borrower
    'APP-CL-X04': ('credit_assessment',    'escalate'), # Foreign national thin file # Foreign national
    'APP-CL-X05': ('product_eligibility',  'block'),    # Short sale seasoning
    'APP-CL-X06': ('credit_assessment',    'escalate'), # Thin file no FICO # Thin file
}


def _parse_args() -> tuple[int, bool]:
    concurrency = CONCURRENCY
    if "--seq" in sys.argv:
        concurrency = 1
    for a in sys.argv:
        if a.startswith("--concurrency="):
            try:
                concurrency = max(1, int(a.split("=", 1)[1]))
            except ValueError:
                pass
    return concurrency, "--direct" in sys.argv


async def main():
    from core.cron.runner import WAVES
    from core.scenarios.runner import ScenarioRunner

    concurrency, direct = _parse_args()
    sr = await ScenarioRunner(
        os.environ["DATABASE_URL"], TENANT, concurrency=concurrency,
        timeout=PER_SCENARIO_TIMEOUT).setup()

    try:
        app_ids = await sr.app_ids()
        print(f"Evaluating {len(app_ids)} capital_loans loans across "
              f"{sum(len(w) for w in WAVES)} decisions "
              f"(concurrency={concurrency}, timeout={PER_SCENARIO_TIMEOUT}s)...")

        def _on_error(r, n):
            print(f"  ! {r[0]}/{r[1]}: {r[2]}")

        errors = await sr.execute(app_ids, on_error=_on_error)
        print(f"decision_outputs written (errors: {len(errors)})\n")

        # Verify expected outcomes
        print("=== SCENARIO VERIFICATION ===")
        passed = 0
        total = 0
        for app_id, (decision_id, expected) in EXPECTED_OUTCOMES.items():
            actual = await sr.conn.fetchval(
                """SELECT outcome FROM decision_outputs
                   WHERE application_id=$1 AND decision_id=$2 AND tenant_id=$3
                   ORDER BY version DESC LIMIT 1""",
                app_id, decision_id, TENANT)
            ok = actual == expected
            passed += 1 if ok else 0
            total += 1
            symbol = "+" if ok else "x"
            print(f"  {symbol}  {app_id} {decision_id}={actual} "
                  f"(expected {expected}) {'PASS' if ok else 'FAIL'}")

        print(f"\nResult: {passed}/{total} scenarios match")

        # Count decision_outputs
        count = await sr.conn.fetchval(
            "SELECT COUNT(*) FROM decision_outputs WHERE tenant_id=$1", TENANT)
        print(f"Total decision_outputs: {count}")

    finally:
        await sr.close()


asyncio.run(main())

"""Seed a realistic underwriter-override pattern for the PROMPT L demo.

Underwriters repeatedly approved Summit loans that Accord escalated on
dti_calculation, each citing compensating factors. The pattern detector
then raises a DTI policy proposal in Policy Studio.

Idempotent — skips an app that already has a compensating_factors approve.

  python scripts/seed_override_pattern.py
"""
import asyncio
import os

from dotenv import load_dotenv

load_dotenv()

TENANT = "summit"
REVIEWER = "underwriter@summit.com"
REASONS = [
    "Borrower has 9 months of reserves and a 762 credit score; DTI is marginally over but compensating factors are strong.",
    "Stable 12-year employment history and a large down payment more than offset the slightly elevated DTI on this file.",
    "Significant liquid reserves and a spotless 24-month payment history justify approval despite the DTI exceedance.",
    "Co-borrower income plus 18 months of reserves comfortably compensate for the DTI being just above the cap.",
    "Excellent credit (758) and documented bonus income support approval even though back-end DTI is a touch high.",
]


async def main():
    import asyncpg
    conn = await asyncpg.connect(
        os.environ['DATABASE_URL'].replace('+asyncpg', '').replace('postgresql+psycopg2', 'postgresql'))
    try:
        apps = await conn.fetch(
            """SELECT DISTINCT application_id FROM decision_outputs
               WHERE tenant_id=$1 AND superseded_by IS NULL
                 AND decision_id='dti_calculation' AND outcome='escalate'
               ORDER BY application_id LIMIT 5""",
            TENANT)
        app_ids = [r['application_id'] for r in apps]
        if len(app_ids) < 3:
            print(f"Only {len(app_ids)} candidate loans — need >= 3 for a pattern.")
            return

        inserted = 0
        for app_id, reason in zip(app_ids, REASONS):
            exists = await conn.fetchval(
                """SELECT 1 FROM loan_actions
                   WHERE tenant_id=$1 AND application_id=$2
                     AND action_type='approve' AND reason_category='compensating_factors'""",
                TENANT, app_id)
            if exists:
                continue
            await conn.execute(
                """INSERT INTO loan_actions
                     (application_id, tenant_id, action_type, reason_category, reason_text,
                      performed_by, related_decision_id, visible_to, performed_at)
                   VALUES ($1,$2,'approve','compensating_factors',$3,$4,'dti_calculation',
                           ARRAY['senior_uw','compliance'], NOW())""",
                app_id, TENANT, reason, REVIEWER)
            inserted += 1

        total = await conn.fetchval(
            "SELECT COUNT(*) FROM loan_actions WHERE tenant_id=$1 AND action_type='approve' "
            "AND reason_category='compensating_factors'", TENANT)
        print(f"Inserted {inserted} approve actions; {total} compensating_factors approvals on {TENANT}.")
        print("Apps:", app_ids[:inserted] if inserted else "(all already present)")
    finally:
        await conn.close()


asyncio.run(main())

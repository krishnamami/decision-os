"""Re-apply the meridian SC08/SC14/SC16 scenario-data fixes.

The EDMS ingest periodically resets meridian entity_states, wiping these
scenario-specific values. Run this AFTER an ingest and BEFORE
evaluate_meridian_scenarios.py so the cascade resolves to the intended
outcomes. Idempotent.

  python scripts/patch_meridian_scenario_data.py

Why each value (the engine propagates upstream blocks downstream, so an
unintended upstream block cascades to the scenario's key decision):

  SC08 credit_assessment=block  — governing_credit_score (LEAST of primary +
        co-borrower mid scores) must be < 580. Set both borrowers to 578.

  SC14 product_eligibility=escalate — VA entitlement gate fires (loan_type='VA')
        AND no upstream block: employer_name_match_confidence >= 0.90 so
        employment auto-verifies (else low-confidence escalate -> income
        contamination block), and verified income raised so dti <= 0.43.

  SC16 closing_readiness=escalate — same upstream unblock as SC14, plus
        fraud_score < 0.5 (rate-lock scenario, not fraud), plus
        days_until_rate_lock_expiry <= 5 so the rate-lock escalate fires.
"""
import asyncio
import os

from dotenv import load_dotenv

load_dotenv()

# (application_id, jsonb_column, path[], json_value_literal)
PATCHES = [
    ('APP-MRID-SC08', 'borrower',   ['credit', 'mid_score'], '578'),

    ('APP-MRID-SC14', 'loan_terms', ['loan_type'], '"VA"'),
    ('APP-MRID-SC14', 'borrower',   ['income', 'verified_income_annual'], '145000'),
    ('APP-MRID-SC14', 'borrower',   ['income', 'income_discrepancy_pct'], '0.0'),
    ('APP-MRID-SC14', 'borrower',   ['employment', 'employer_name_match_confidence'], '0.95'),

    ('APP-MRID-SC16', 'borrower',   ['identity', 'fraud_score'], '0.15'),
    ('APP-MRID-SC16', 'borrower',   ['income', 'verified_income_annual'], '160000'),
    ('APP-MRID-SC16', 'borrower',   ['income', 'income_discrepancy_pct'], '0.0'),
    ('APP-MRID-SC16', 'borrower',   ['employment', 'employer_name_match_confidence'], '0.95'),
    ('APP-MRID-SC16', 'loan_terms', ['days_until_rate_lock_expiry'], '3'),
]


async def main():
    import asyncpg
    url = os.environ['DATABASE_URL'].replace('+asyncpg', '').replace('postgresql+psycopg2', 'postgresql')
    conn = await asyncpg.connect(url)
    try:
        for app, col, path, value in PATCHES:
            await conn.execute(
                f"UPDATE entity_states SET {col} = jsonb_set({col}, $1, $2::jsonb) "
                f"WHERE application_id = $3 AND tenant_id = 'meridian'",
                path, value, app)
        print(f"applied {len(PATCHES)} scenario-data patches for SC08/SC14/SC16")
    finally:
        await conn.close()


asyncio.run(main())

"""Patch the 16 meridian loans with scenario-spec values directly in
entity_states. Adapted to the real schema: the obligations column is
`monthly_obligations` (there is no `total_obligations`), and
property_state / loan_purpose are written into the loan_terms jsonb
(neither is a real column).

  python scripts/patch_meridian_entity_states.py
"""
import asyncio
import os

from dotenv import load_dotenv

load_dotenv()

# app_id, qualifying_monthly, obligations, dti_back(%), property_state, loan_purpose
PATCHES = [
    ('APP-MRID-SC01', 8000,  1800, 22.5, 'TX', 'purchase'),
    ('APP-MRID-SC02', 9000,  3942, 43.8, 'TX', 'purchase'),
    ('APP-MRID-SC03', 11500, 3450, 30.0, 'TX', 'purchase'),
    ('APP-MRID-SC04', 7333,  2200, 30.0, 'TX', 'purchase'),
    ('APP-MRID-SC05', 12083, 3200, 26.5, 'TX', 'cash_out_refinance'),
    ('APP-MRID-SC06', 6500,  1950, 30.0, 'TX', 'purchase'),
    ('APP-MRID-SC07', 8500,  3740, 44.0, 'TX', 'purchase'),
    ('APP-MRID-SC08', 11250, 2800, 24.9, 'TX', 'purchase'),
    ('APP-MRID-SC09', 9333,  2650, 28.4, 'TX', 'purchase'),
    ('APP-MRID-SC10', 9833,  2900, 29.5, 'TX', 'purchase'),
    ('APP-MRID-SC11', 8500,  3803, 44.7, 'TX', 'purchase'),
    ('APP-MRID-SC12', 6200,  2976, 48.0, 'TX', 'purchase'),
    ('APP-MRID-SC13', 7667,  2300, 30.0, 'TX', 'purchase'),
    ('APP-MRID-SC14', 7333,  1950, 26.6, 'TX', 'purchase'),
    ('APP-MRID-SC15', 7000,  2100, 30.0, 'TX', 'purchase'),
    ('APP-MRID-SC16', 8000,  2400, 30.0, 'TX', 'purchase'),
]


async def main():
    import asyncpg
    url = os.environ['DATABASE_URL'].replace('+asyncpg', '').replace('postgresql+psycopg2', 'postgresql')
    conn = await asyncpg.connect(url)

    cols = await conn.fetch(
        "SELECT column_name FROM information_schema.columns WHERE table_name='entity_states'")
    col_names = [r['column_name'] for r in cols]
    obl_col = 'total_obligations' if 'total_obligations' in col_names else 'monthly_obligations'
    print(f"obligations column in use: {obl_col}")
    print(f"property_state column exists: {'property_state' in col_names}")
    print(f"loan_purpose column exists:   {'loan_purpose' in col_names}\n")

    for app_id, income, oblig, dti, state, purpose in PATCHES:
        await conn.execute(
            f"""UPDATE entity_states
                SET qualifying_monthly=$1, {obl_col}=$2, dti_back=$3
                WHERE application_id=$4 AND tenant_id='meridian'""",
            income, oblig, dti, app_id)
        # property_state + loan_purpose into loan_terms jsonb (no real columns)
        await conn.execute(
            """UPDATE entity_states
               SET loan_terms = jsonb_set(
                     jsonb_set(COALESCE(loan_terms,'{}'::jsonb),
                               '{property_state}', to_jsonb($1::text)),
                     '{loan_purpose}', to_jsonb($2::text))
               WHERE application_id=$3 AND tenant_id='meridian'""",
            state, purpose, app_id)
        print(f"  {app_id}: income={income} oblig={oblig} dti={dti} state={state} purpose={purpose}")

    rows = await conn.fetch(
        f"""SELECT application_id, mid_credit_score, dti_back, qualifying_monthly,
                   {obl_col} AS obligations,
                   loan_terms->>'property_state' AS prop_state,
                   loan_terms->>'loan_purpose' AS loan_purpose
            FROM entity_states WHERE tenant_id='meridian' ORDER BY application_id""")
    print("\nVerification:")
    print(f"{'app_id':<16}{'credit':>7}{'dti':>7}{'income':>9}{'oblig':>8}{'state':>7}  purpose")
    print("-" * 70)
    for r in rows:
        print(f"{r['application_id']:<16}{str(r['mid_credit_score']):>7}"
              f"{str(round(float(r['dti_back'] or 0),1)):>7}{str(r['qualifying_monthly']):>9}"
              f"{str(r['obligations']):>8}{str(r['prop_state'] or '?'):>7}  {r['loan_purpose'] or '?'}")
    await conn.close()
    print("\nDone. Re-run evaluate_meridian_scenarios.py next.")


asyncio.run(main())

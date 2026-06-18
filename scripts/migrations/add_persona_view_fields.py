"""Add missing entity_states fields to 4 persona context views + fix the
meridian loan_terms.urla data so the compliance view reads property_state.

Views updated (CREATE OR REPLACE, columns appended at the end):
  vw_credit_assessment_context   : governing_credit_score (MIN primary+co-borrower)
  vw_income_verification_context : income_type, rental_income_qualifying
  vw_product_eligibility_context : va_entitlement_used, va_entitlement_remaining
  vw_closing_readiness_context   : rate_lock_expiry, cd_delivery_date, closing_date

Each view is replaced by reading its CURRENT definition (pg_get_viewdef) and
injecting the new columns before FROM — so the exact existing SELECT (incl. the
credit view's monthly_obligations CASE) is preserved verbatim. Idempotent:
a column already present is skipped.

Data fix: the compliance view reads loan_terms->'urla'->>'property_state', but
earlier data put it at top-level loan_terms->>'property_state'. Move
property_state/loan_purpose into loan_terms.urla for all 16 meridian loans.

  python scripts/migrations/add_persona_view_fields.py
"""
import asyncio
import os

from dotenv import load_dotenv

load_dotenv()

ES = "entity_states"
NEW_COLS = {
    "vw_credit_assessment_context": [
        f"LEAST({ES}.mid_credit_score, COALESCE(({ES}.co_borrowers -> 0 ->> 'mid_credit_score')::integer, {ES}.mid_credit_score)) AS governing_credit_score",
    ],
    "vw_income_verification_context": [
        f"{ES}.borrower ->> 'income_type' AS income_type",
        f"({ES}.loan_terms ->> 'rental_income_qualifying')::double precision AS rental_income_qualifying",
    ],
    "vw_product_eligibility_context": [
        f"({ES}.loan_terms ->> 'va_entitlement_used')::double precision AS va_entitlement_used",
        f"({ES}.loan_terms ->> 'va_entitlement_remaining')::double precision AS va_entitlement_remaining",
    ],
    "vw_closing_readiness_context": [
        f"{ES}.loan_terms ->> 'rate_lock_expiry' AS rate_lock_expiry",
        f"{ES}.loan_terms ->> 'cd_delivery_date' AS cd_delivery_date",
        f"{ES}.loan_terms ->> 'closing_date' AS closing_date",
    ],
}

LOAN_PURPOSES = {f"APP-MRID-SC{n:02d}": "cash_out_refinance" if n == 5 else "purchase" for n in range(1, 17)}


def _u():
    return os.environ["DATABASE_URL"].replace("+asyncpg", "").replace("postgresql+psycopg2", "postgresql")


async def main():
    import asyncpg
    conn = await asyncpg.connect(_u())
    try:
        # ── Thing A: append columns to the 4 views ──
        for view, cols in NEW_COLS.items():
            defn = await conn.fetchval("SELECT pg_get_viewdef($1, true)", view)
            missing = [c for c in cols if (" AS " + c.split(" AS ")[-1]) not in defn]
            if not missing:
                print(f"{view}: already has all new columns, skipping")
                continue
            idx = defn.rfind("FROM entity_states")
            select_part = defn[:idx].rstrip()           # ends with last column, no comma
            tail = defn[idx:]                            # "FROM entity_states;"
            new_select = select_part + ",\n    " + ",\n    ".join(missing) + "\n   " + tail
            await conn.execute(f"CREATE OR REPLACE VIEW {view} AS {new_select}")
            print(f"{view}: added {[c.split(' AS ')[-1] for c in missing]}")

        # ── Thing B: move property_state/loan_purpose into loan_terms.urla ──
        for app_id, purpose in LOAN_PURPOSES.items():
            await conn.execute(
                """
                UPDATE entity_states
                SET loan_terms = jsonb_set(
                    COALESCE(loan_terms, '{}'::jsonb), '{urla}',
                    COALESCE(loan_terms -> 'urla', '{}'::jsonb)
                    || jsonb_build_object(
                        'property_state', 'TX',
                        'loan_purpose', $1::text,
                        'loan_type', COALESCE(loan_terms ->> 'loan_type', 'Conventional')
                    ))
                WHERE application_id = $2 AND tenant_id = 'meridian'
                """,
                purpose, app_id)
        # SC05 is explicitly Conventional cash-out (loan_type override).
        await conn.execute(
            """UPDATE entity_states
               SET loan_terms = jsonb_set(loan_terms, '{urla,loan_type}', '\"Conventional\"'::jsonb)
               WHERE application_id='APP-MRID-SC05' AND tenant_id='meridian'""")
        print("data fix: 16 loans -> loan_terms.urla.property_state/loan_purpose set")

        # ── Verify ──
        print("\n=== new view columns ===")
        rows = await conn.fetch("""
            SELECT table_name, column_name FROM information_schema.columns
            WHERE table_name = ANY($1) AND column_name = ANY($2)
            ORDER BY table_name, column_name""",
            list(NEW_COLS.keys()),
            ['governing_credit_score', 'income_type', 'rental_income_qualifying',
             'va_entitlement_used', 'va_entitlement_remaining',
             'rate_lock_expiry', 'cd_delivery_date', 'closing_date'])
        for r in rows:
            print(f"  {r['table_name']}.{r['column_name']}")
        print("\n=== SC05 urla ===")
        r = await conn.fetchrow(
            "SELECT loan_terms->'urla'->>'property_state' s, loan_terms->'urla'->>'loan_purpose' p, ltv "
            "FROM entity_states WHERE application_id='APP-MRID-SC05' AND tenant_id='meridian'")
        print(f"  state={r['s']} purpose={r['p']} ltv={r['ltv']}")
    finally:
        await conn.close()


asyncio.run(main())

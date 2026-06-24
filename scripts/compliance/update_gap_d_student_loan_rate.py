"""
OB-A Part 1 / Gap (d) — update the student-loan DEFERRED rate 1.0% -> 0.5%.

ARCHITECTURE.md gap (d): the catalogue seeded student_loan_deferred_rate_pct=1.0,
but current Fannie B3-6-05 uses a 0.5% floor for $0 / unreported deferred payments.
The value is read by core/credit/tradeline_analyzer._student_loan_rate (value / 100),
so this is a one-row catalogue correction — no code change, value-equivalent in the
resolver. 0 meridian apps carry student-loan tradelines, so 16/16 is unaffected.

guideline_value is JSONB {type,unit,value}; we update only the `value` field via
jsonb_set so the shape is preserved (a bare '0.5' string would break get_rule's
parser). Idempotent — no-op if already 0.5.

  python scripts/compliance/update_gap_d_student_loan_rate.py
"""
import asyncio
import os
from dotenv import load_dotenv
load_dotenv()


def _u():
    return os.environ["DATABASE_URL"].replace("+asyncpg", "").replace(
        "postgresql+psycopg2", "postgresql")


async def main():
    import asyncpg
    conn = await asyncpg.connect(_u())
    try:
        before = await conn.fetchval(
            """SELECT guideline_value FROM agency_guidelines
               WHERE guideline_name='student_loan_deferred_rate_pct'
               AND valid_to IS NULL AND is_active=true""")
        print(f"BEFORE: student_loan_deferred_rate_pct = {before}")
        await conn.execute(
            """UPDATE agency_guidelines
               SET guideline_value = jsonb_set(guideline_value, '{value}', '0.5'::jsonb),
                   display_value = '0.5%',
                   last_verified = CURRENT_DATE,
                   source_revision = 'OB-A gap(d)'
               WHERE guideline_name='student_loan_deferred_rate_pct'
                 AND valid_to IS NULL AND is_active=true""")
        for r in await conn.fetch(
            """SELECT guideline_name, guideline_value, citation FROM agency_guidelines
               WHERE guideline_name='student_loan_deferred_rate_pct'
               AND valid_to IS NULL AND is_active=true"""):
            print(f"AFTER:  {r['guideline_name']} = {r['guideline_value']}  [{r['citation']}]")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())

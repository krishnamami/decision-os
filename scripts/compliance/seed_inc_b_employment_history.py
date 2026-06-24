"""
INC-B — seed the W2 employment-history requirement so W2IncomeResolver reads it
from the catalogue instead of a Python literal (RULE 8: catalogue before code).

  employment_history_months_required = 24  (Fannie B3-3.1-01)

Fannie requires a 2-year (24-month) employment / income history for W2 income.
snake_case name matches the resolver key + the existing income-family sibling
`se_income_years_required` (also snake_case). Idempotent existence-check.

  python scripts/compliance/seed_inc_b_employment_history.py
"""
import asyncio
import json
import os
from dotenv import load_dotenv
load_dotenv()

ROWS = [
    ("fannie", "income", "employment_history_months_required", 24, "24 months",
     "A 2-year (24-month) employment / income history is required to qualify W2 "
     "and salaried income; a shorter history needs documentation of the gap or "
     "prior schooling/training.",
     "Fannie Mae Selling Guide B3-3.1-01"),
]


def _gv(value) -> str:
    if isinstance(value, bool):
        return json.dumps({"type": "boolean", "value": value})
    if isinstance(value, (int, float)):
        return json.dumps({"type": "threshold", "value": value})
    return json.dumps({"type": "treatment", "value": value})


def _u():
    return os.environ["DATABASE_URL"].replace("+asyncpg", "").replace(
        "postgresql+psycopg2", "postgresql")


async def main():
    import asyncpg
    conn = await asyncpg.connect(_u())
    try:
        print("-- seed agency_guidelines (INC-B employment history) --")
        for agency, cat, name, value, disp, desc, cite in ROWS:
            exists = await conn.fetchval(
                """SELECT 1 FROM agency_guidelines
                   WHERE agency=$1 AND guideline_name=$2
                   AND valid_to IS NULL AND is_active = true LIMIT 1""",
                agency, name,
            )
            if exists:
                print(f"  {agency}/{name}: already present, skipping")
                continue
            await conn.execute(
                """INSERT INTO agency_guidelines
                   (agency, category, guideline_name, guideline_value,
                    display_value, description, citation, source_url,
                    effective_date, last_verified, verified_by,
                    valid_from, source_revision)
                   VALUES ($1,$2,$3,$4::jsonb,$5,$6,$7,
                           'https://selling-guide.fanniemae.com',
                           CURRENT_DATE, CURRENT_DATE, 'Accord compliance team',
                           CURRENT_DATE, 'INC-B')""",
                agency, cat, name, _gv(value), disp, desc, cite,
            )
            print(f"  {agency}/{name} = {value} (inserted)  [{cite}]")

        print("\n-- verify --")
        for r in await conn.fetch(
            """SELECT guideline_name, guideline_value, citation
               FROM agency_guidelines
               WHERE source_revision='INC-B' AND valid_to IS NULL
               ORDER BY guideline_name"""):
            print(f"  {r['guideline_name']}: {r['guideline_value']}  [{r['citation']}]")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())

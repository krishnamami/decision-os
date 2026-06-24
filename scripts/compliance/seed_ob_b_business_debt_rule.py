"""
OB-B — seed the business-debt exclusion threshold the ObligationResolver reads
(RULE 8). Fannie B3-6-05 (debts paid by others / the business): a debt on the
borrower's personal credit report may be EXCLUDED from DTI when the business (or
another party) has paid it for >=12 months with no 30-day delinquency, evidenced
by cancelled checks / bank statements.

  business_debt_exclusion_months = 12  (Fannie B3-6-05)

Rental mortgage offset needs NO new threshold (structural per B3-3.1-08; the
rental_vacancy_factor_pct=25 already exists). HELOC factor already seeded (OB-A).
agency layer, category 'income'. Idempotent; JSONB threshold shape.

  python scripts/compliance/seed_ob_b_business_debt_rule.py
"""
import asyncio
import json
import os
from dotenv import load_dotenv
load_dotenv()

_CITE = "Fannie Mae Selling Guide B3-6-05"
ROWS = [
    ("business_debt_exclusion_months", 12, "12 months",
     "A debt on the borrower's personal credit report may be excluded from DTI "
     "when the business (or another obligor) has paid it for at least 12 months "
     "with no 30-day delinquency, evidenced by cancelled checks / bank statements."),
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
        print("-- seed agency_guidelines (OB-B business-debt exclusion) --")
        for name, value, disp, desc in ROWS:
            exists = await conn.fetchval(
                """SELECT 1 FROM agency_guidelines
                   WHERE agency='fannie' AND guideline_name=$1
                   AND valid_to IS NULL AND is_active = true LIMIT 1""", name)
            if exists:
                print(f"  fannie/{name}: already present, skipping")
                continue
            await conn.execute(
                """INSERT INTO agency_guidelines
                   (agency, category, guideline_name, guideline_value,
                    display_value, description, citation, source_url,
                    effective_date, last_verified, verified_by,
                    valid_from, source_revision)
                   VALUES ('fannie','income',$1,$2::jsonb,$3,$4,$5,
                           'https://selling-guide.fanniemae.com',
                           CURRENT_DATE, CURRENT_DATE, 'Accord compliance team',
                           CURRENT_DATE, 'OB-B')""",
                name, _gv(value), disp, desc, _CITE)
            print(f"  fannie/{name} = {value} (inserted)  [{_CITE}]")

        print("\n-- verify --")
        for r in await conn.fetch(
            """SELECT guideline_name, guideline_value FROM agency_guidelines
               WHERE source_revision='OB-B' AND valid_to IS NULL ORDER BY guideline_name"""):
            print(f"  {r['guideline_name']}: {r['guideline_value']}")
        total = await conn.fetchval(
            "SELECT COUNT(*) FROM agency_guidelines WHERE valid_to IS NULL AND is_active=true")
        print(f"\n  total active agency_guidelines: {total}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())

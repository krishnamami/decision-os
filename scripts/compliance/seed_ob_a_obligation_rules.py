"""
OB-A Part 2 — seed the obligation payment-factor rules the ObligationResolver
reads (RULE 8). Fannie B3-6-02 monthly-debt-obligation guidance:
  revolving_payment_factor_pct = 5  (5% of balance when no min payment is reported)
  heloc_payment_factor_pct     = 1  (1% of credit limit when in draw period / $0 bal)

Installment (balance / months_remaining) + the ≤10-month exclusion
(Installment Debt Months Remaining Exclusion, already seeded) need no new rule.
Student-loan + alimony/child-support paid reuse existing resolvers. agency layer,
category 'income'. Idempotent; JSONB factor shape.

  python scripts/compliance/seed_ob_a_obligation_rules.py
"""
import asyncio
import json
import os
from dotenv import load_dotenv
load_dotenv()

_CITE = "Fannie Mae Selling Guide B3-6-02"

ROWS = [
    ("revolving_payment_factor_pct", 5, "5%",
     "When a credit report shows no monthly payment for a revolving account, use "
     "5% of the outstanding balance as the monthly obligation for DTI."),
    ("heloc_payment_factor_pct", 1, "1%",
     "For a HELOC in its draw period (or with no reported payment), use 1% of the "
     "outstanding balance / credit line as the monthly obligation for DTI."),
]


def _gv(value) -> str:
    if isinstance(value, bool):
        return json.dumps({"type": "boolean", "value": value})
    if isinstance(value, (int, float)):
        return json.dumps({"type": "factor", "unit": "percent", "value": value})
    return json.dumps({"type": "treatment", "value": value})


def _u():
    return os.environ["DATABASE_URL"].replace("+asyncpg", "").replace(
        "postgresql+psycopg2", "postgresql")


async def main():
    import asyncpg
    conn = await asyncpg.connect(_u())
    try:
        print("-- seed agency_guidelines (OB-A obligation factors) --")
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
                           CURRENT_DATE, 'OB-A')""",
                name, _gv(value), disp, desc, _CITE)
            print(f"  fannie/{name} = {value} (inserted)  [{_CITE}]")

        print("\n-- verify (OB-A rows) --")
        for r in await conn.fetch(
            """SELECT guideline_name, guideline_value FROM agency_guidelines
               WHERE source_revision='OB-A' AND valid_to IS NULL ORDER BY guideline_name"""):
            print(f"  {r['guideline_name']}: {r['guideline_value']}")
        total = await conn.fetchval(
            "SELECT COUNT(*) FROM agency_guidelines WHERE valid_to IS NULL AND is_active=true")
        print(f"\n  total active agency_guidelines: {total}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())

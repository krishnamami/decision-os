"""
INC-F — seed the alimony / child-support rules the AlimonyChildSupportResolver
reads (RULE 8: catalogue before code). Fannie B3-3.1-09 (received income 3-yr
continuance) + B3-6-05 (alimony paid DTI treatment). agency layer, category
'income'. Idempotent; JSONB threshold/treatment shape (matches prior seeds).

  alimony_continuance_months_required       = 36            (B3-3.1-09)
  child_support_continuance_months_required = 36            (B3-3.1-09)
  alimony_paid_dti_treatment                = 'monthly_debt' (B3-6-05)

Only the THREE functional rules the resolver reads (ALIMONY_RULE_KEYS) are seeded.
The prompt's 4th "alimony_received_min_continuance_note" is a prose note, not a
threshold/treatment any code reads, so it is intentionally NOT seeded (the 3-yr
rule already carries that meaning via its value + citation).

  python scripts/compliance/seed_inc_f_alimony_rules.py
"""
import asyncio
import json
import os
from dotenv import load_dotenv
load_dotenv()

# (guideline_name, value, display, description, citation)
ROWS = [
    ("alimony_continuance_months_required", 36, "36 months",
     "Alimony / spousal-support income must be expected to continue at least 3 "
     "years from closing to be used for qualifying.",
     "Fannie Mae Selling Guide B3-3.1-09"),
    ("child_support_continuance_months_required", 36, "36 months",
     "Child-support income must be expected to continue at least 3 years from "
     "closing to be used for qualifying.",
     "Fannie Mae Selling Guide B3-3.1-09"),
    ("alimony_paid_dti_treatment", "monthly_debt", "monthly_debt",
     "Alimony PAID is treated as a monthly debt obligation in DTI (the lender "
     "may alternatively reduce gross income — 'reduce_income' — per B3-6-05).",
     "Fannie Mae Selling Guide B3-6-05"),
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
        print("-- seed agency_guidelines (INC-F alimony / child support) --")
        for name, value, disp, desc, cite in ROWS:
            exists = await conn.fetchval(
                """SELECT 1 FROM agency_guidelines
                   WHERE agency='fannie' AND guideline_name=$1
                   AND valid_to IS NULL AND is_active = true LIMIT 1""",
                name,
            )
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
                           CURRENT_DATE, 'INC-F')""",
                name, _gv(value), disp, desc, cite,
            )
            print(f"  fannie/{name} = {value} (inserted)  [{cite}]")

        print("\n-- verify (INC-F rows) --")
        for r in await conn.fetch(
            """SELECT guideline_name, guideline_value FROM agency_guidelines
               WHERE source_revision='INC-F' AND valid_to IS NULL
               ORDER BY guideline_name"""):
            print(f"  {r['guideline_name']}: {r['guideline_value']}")
        total = await conn.fetchval(
            "SELECT COUNT(*) FROM agency_guidelines WHERE valid_to IS NULL AND is_active=true")
        print(f"\n  total active agency_guidelines: {total}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())

"""MI-E (RULE 8) — seed non-occupant co-borrower rules into agency_guidelines.

Fannie B2-2-04: when a co-borrower does NOT occupy the property, conventional LTV is
capped and the OCCUPANT borrower's own ratios must independently support the loan.

  non_occupant_co_borrower_max_ltv_pct           = 95   (Fannie B2-2-04)
  non_occupant_co_borrower_occupant_must_qualify = true (Fannie B2-2-04)

Idempotent; JSONB; agency layer, category 'income'. Run:
  PYTHONIOENCODING=utf-8 PYTHONUTF8=1 python scripts/compliance/seed_mi_e_multi_borrower_rules.py
"""
import asyncio
import json
import os

from dotenv import load_dotenv

load_dotenv()

_CITE = "Fannie Mae Selling Guide B2-2-04"
ROWS = [
    ("non_occupant_co_borrower_max_ltv_pct", 95, "95%",
     "Conventional LTV is capped at 95% when a non-occupant co-borrower is present."),
    ("non_occupant_co_borrower_occupant_must_qualify", True, "true",
     "The occupant borrower's ratios must independently support the loan when a "
     "non-occupant co-borrower is on the application."),
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
        print("-- seed agency_guidelines (MI-E non-occupant co-borrower) --")
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
                           CURRENT_DATE, 'MI-E')""",
                name, _gv(value), disp, desc, _CITE)
            print(f"  fannie/{name} = {value} (inserted)  [{_CITE}]")

        print("\n-- verify --")
        for r in await conn.fetch(
            """SELECT guideline_name, guideline_value, citation FROM agency_guidelines
               WHERE source_revision='MI-E' AND valid_to IS NULL ORDER BY guideline_name"""):
            print(f"  {r['guideline_name']}: {r['guideline_value']}  ({r['citation']})")
        total = await conn.fetchval(
            "SELECT COUNT(*) FROM agency_guidelines WHERE valid_to IS NULL AND is_active=true")
        print(f"\n  total active agency_guidelines: {total}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())

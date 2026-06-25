"""CO-D (RULE 8) — seed ADU + multi-unit rental income rules into agency_guidelines.

Lets MultiUnitIncomeResolver read its factors from the catalogue (RULE 1/9) rather
than hardcoding 75% / occupancy rules.

  market_rent_qualifying_factor_pct = 75   (Fannie B3-3.1-08 / Form 1007 — 75% of gross market rent)
  subject_2_4_unit_rental_factor    = 75   (Fannie B3-3.1-08 — 75% gross market rent, subject 2-4 unit)
  adu_rental_income_allowed         = true (Fannie HomeReady B5-6-01)
  adu_owner_occupancy_required      = true (Fannie HomeReady B5-6-01 — borrower must occupy)
  adu_max_units                     = 1    (Fannie HomeReady — one ADU per property)

Idempotent; JSONB shape; agency layer, category 'income'. Run:
  PYTHONIOENCODING=utf-8 PYTHONUTF8=1 python scripts/compliance/seed_co_d_multi_unit_rules.py
"""
import asyncio
import json
import os

from dotenv import load_dotenv

load_dotenv()

ROWS = [
    ("market_rent_qualifying_factor_pct", 75, "75%",
     "Qualifying rental income is 75% of gross market rent (Form 1007/1025).",
     "Fannie Mae Selling Guide B3-3.1-08"),
    ("subject_2_4_unit_rental_factor", 75, "75%",
     "Subject 2-4 unit owner-occupied: 75% of gross market rent from rental units.",
     "Fannie Mae Selling Guide B3-3.1-08"),
    ("adu_rental_income_allowed", True, "true",
     "ADU (accessory dwelling unit) rental income may be used to qualify (HomeReady).",
     "Fannie Mae Selling Guide B5-6-01"),
    ("adu_owner_occupancy_required", True, "true",
     "ADU income requires the borrower to occupy the primary dwelling (HomeReady).",
     "Fannie Mae Selling Guide B5-6-01"),
    ("adu_max_units", 1, "1",
     "One ADU per property is eligible for income consideration (HomeReady).",
     "Fannie Mae Selling Guide B5-6-01"),
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
        print("-- seed agency_guidelines (CO-D ADU + multi-unit rules) --")
        for name, value, disp, desc, cite in ROWS:
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
                           CURRENT_DATE, 'CO-D')""",
                name, _gv(value), disp, desc, cite)
            print(f"  fannie/{name} = {value} (inserted)  [{cite}]")

        print("\n-- verify --")
        for r in await conn.fetch(
            """SELECT guideline_name, guideline_value, citation FROM agency_guidelines
               WHERE source_revision='CO-D' AND valid_to IS NULL ORDER BY guideline_name"""):
            print(f"  {r['guideline_name']}: {r['guideline_value']}  ({r['citation']})")
        total = await conn.fetchval(
            "SELECT COUNT(*) FROM agency_guidelines WHERE valid_to IS NULL AND is_active=true")
        print(f"\n  total active agency_guidelines: {total}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())

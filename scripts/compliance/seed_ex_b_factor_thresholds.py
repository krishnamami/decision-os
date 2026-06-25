"""
EX-B — seed the 6 compensating-factor bar thresholds the CompensatingFactorsEngine
reads (RULE 8). Fannie B3-2-02 (DU / compensating factors). agency layer, category
'exception'. Idempotent; JSONB threshold shape. Baseline floors (minimum_reserves_months=2,
Minimum Credit Score=620, LTV maxes) already exist and are reused as the measuring sticks.

  substantial_reserves_months       = 6   (moderate reserves CF)
  exceptional_reserves_months       = 12  (strong reserves CF)
  low_ltv_factor_max_pct            = 75  (LTV <= 75% is a strong CF)
  excellent_credit_delta_pts        = 60  (score >= floor+60 is a strong CF)
  long_employment_months            = 60  (5yr same employer is a CF)
  minimal_debt_obligations_max_pct  = 10  (obligations/income < 10% is a CF)

  python scripts/compliance/seed_ex_b_factor_thresholds.py
"""
import asyncio
import json
import os
from dotenv import load_dotenv
load_dotenv()

_CITE = "Fannie Mae Selling Guide B3-2-02"
ROWS = [
    ("substantial_reserves_months", 6, "6 months",
     "6+ months of PITI in reserves is a moderate compensating factor."),
    ("exceptional_reserves_months", 12, "12 months",
     "12+ months of PITI in reserves is a strong compensating factor."),
    ("low_ltv_factor_max_pct", 75, "75%",
     "An LTV at or below 75% is a strong compensating factor (significant equity)."),
    ("excellent_credit_delta_pts", 60, "60 points",
     "A credit score 60+ points above the minimum is a strong compensating factor."),
    ("long_employment_months", 60, "60 months",
     "5+ years (60 months) with the same employer is a compensating factor."),
    ("minimal_debt_obligations_max_pct", 10, "10%",
     "Monthly obligations below 10% of qualifying income is a compensating factor."),
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
        print("-- seed agency_guidelines (EX-B compensating-factor thresholds) --")
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
                   VALUES ('fannie','exception',$1,$2::jsonb,$3,$4,$5,
                           'https://selling-guide.fanniemae.com',
                           CURRENT_DATE, CURRENT_DATE, 'Accord compliance team',
                           CURRENT_DATE, 'EX-B')""",
                name, _gv(value), disp, desc, _CITE)
            print(f"  fannie/{name} = {value} (inserted)  [{_CITE}]")

        print("\n-- verify --")
        for r in await conn.fetch(
            """SELECT guideline_name, guideline_value FROM agency_guidelines
               WHERE source_revision='EX-B' AND valid_to IS NULL ORDER BY guideline_name"""):
            print(f"  {r['guideline_name']}: {r['guideline_value']}")
        total = await conn.fetchval(
            "SELECT COUNT(*) FROM agency_guidelines WHERE valid_to IS NULL AND is_active=true")
        print(f"\n  total active agency_guidelines: {total}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())

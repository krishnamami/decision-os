"""
EX-A — seed the exception-framework thresholds the ExceptionEngine reads
(RULE 8). Fannie B3-2-02 (DU / underwriting exceptions + compensating factors).
agency layer, category 'exception'. Idempotent; JSONB boolean/threshold shape.

  exception_requires_compensating_factors = true (B3-2-02)
  exception_max_dti_overlay_breach_pct     = 5    (overlay breach tolerance)
  exception_max_ltv_overlay_breach_pct     = 5
  exception_cannot_breach_agency_floor     = true (agency minimums are absolute)

  python scripts/compliance/seed_ex_a_exception_rules.py
"""
import asyncio
import json
import os
from dotenv import load_dotenv
load_dotenv()

_CITE = "Fannie Mae Selling Guide B3-2-02"
ROWS = [
    ("exception_requires_compensating_factors", True, "true",
     "An underwriting exception (overlay breach) requires at least one documented "
     "compensating factor before it may be granted."),
    ("exception_max_dti_overlay_breach_pct", 5, "5%",
     "Maximum percentage by which DTI may exceed the lender overlay and still be "
     "eligible for an exception (above this, no exception)."),
    ("exception_max_ltv_overlay_breach_pct", 5, "5%",
     "Maximum percentage by which LTV may exceed the lender overlay and still be "
     "eligible for an exception."),
    ("exception_cannot_breach_agency_floor", True, "true",
     "Agency minimums are absolute — an exception can never go below the agency "
     "floor, regardless of compensating factors."),
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
        print("-- seed agency_guidelines (EX-A exception framework) --")
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
                           CURRENT_DATE, 'EX-A')""",
                name, _gv(value), disp, desc, _CITE)
            print(f"  fannie/{name} = {value} (inserted)  [{_CITE}]")

        print("\n-- verify --")
        for r in await conn.fetch(
            """SELECT guideline_name, guideline_value FROM agency_guidelines
               WHERE source_revision='EX-A' AND valid_to IS NULL ORDER BY guideline_name"""):
            print(f"  {r['guideline_name']}: {r['guideline_value']}")
        total = await conn.fetchval(
            "SELECT COUNT(*) FROM agency_guidelines WHERE valid_to IS NULL AND is_active=true")
        print(f"\n  total active agency_guidelines: {total}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())

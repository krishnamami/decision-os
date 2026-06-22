"""
Seed income documentation confidence thresholds into agency_guidelines
(RA-3D correction). These are agency documentation standards (Fannie Mae
B3-3.1-01), read by income_verification via rule_loader — not Python constants.

Idempotent: existence-checked by (agency, guideline_name, current version).
There is no unique constraint on (agency, guideline_name) (Type 2 SCD keeps
history), so we cannot use ON CONFLICT — we SELECT-then-INSERT.

  python scripts/compliance/seed_income_doc_thresholds.py
"""
import asyncio
import json
import os
from datetime import date
from dotenv import load_dotenv
load_dotenv()

# (agency, name, value, display, description, citation)
ROWS = [
    ("fannie", "income_documentation_confidence_min", 0.75, "0.75",
     "Minimum evidence confidence to use document-derived income. Below this "
     "threshold additional documentation is required per Fannie income "
     "verification standards.",
     "Fannie Mae Selling Guide B3-3.1-01"),
    ("fannie", "income_documentation_confidence_floor", 0.50, "0.50",
     "Floor confidence below which document-derived income cannot be used and "
     "manual verification is required.",
     "Fannie Mae Selling Guide B3-3.1-01"),
]


def _u():
    return os.environ["DATABASE_URL"].replace("+asyncpg", "").replace(
        "postgresql+psycopg2", "postgresql")


async def main():
    import asyncpg
    conn = await asyncpg.connect(_u())
    try:
        for agency, name, value, disp, desc, cite in ROWS:
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
                   VALUES ($1,'income',$2,$3::jsonb,$4,$5,$6,
                           'https://selling-guide.fanniemae.com/sel/b3-3.1-01/general-income-information',
                           CURRENT_DATE, CURRENT_DATE, 'Accord compliance team',
                           CURRENT_DATE, 'RA-3D')""",
                agency, name,
                json.dumps({"type": "threshold", "value": value}),
                disp, desc, cite,
            )
            print(f"  {agency}/{name} = {value} (inserted)")

        print("\n=== verify ===")
        for r in await conn.fetch(
            """SELECT agency, guideline_name, guideline_value, citation
               FROM agency_guidelines
               WHERE guideline_name ILIKE 'income_documentation_confidence%'
               AND valid_to IS NULL ORDER BY guideline_name"""
        ):
            print(f"  {r['agency']}/{r['guideline_name']}: "
                  f"{r['guideline_value']}  [{r['citation']}]")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())

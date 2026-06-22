"""
Seed income mismatch severity thresholds into agency_guidelines (RA-3E).

These mirror the platform_guardrails risk thresholds (RA-1) but are placed in
agency_guidelines with a Fannie citation so the fraud_resolver can read them
through rule_loader.get_rule (the authoritative path) rather than the
SAFE_DEFAULTS fallback. Idempotent existence-check (no unique constraint on
agency,guideline_name — Type 2 keeps history).

  python scripts/compliance/seed_income_mismatch_thresholds.py
"""
import asyncio
import json
import os
from dotenv import load_dotenv
load_dotenv()

# (agency, name, value, display, description)
ROWS = [
    ("fannie", "income_mismatch_medium_pct", 10, "10%",
     "Income variance (URLA vs verified) at or above this percent triggers a "
     "medium-severity mismatch review per Fannie QC standards."),
    ("fannie", "income_mismatch_high_pct", 25, "25%",
     "Income variance at or above this percent triggers a high-severity "
     "income inflation flag."),
    ("fannie", "income_mismatch_critical_pct", 50, "50%",
     "Income variance at or above this percent is a critical fraud signal "
     "requiring escalation / auto-block."),
]
CITE = "Fannie Mae Selling Guide B3-3.1-01 / QC standards"


def _u():
    return os.environ["DATABASE_URL"].replace("+asyncpg", "").replace(
        "postgresql+psycopg2", "postgresql")


async def main():
    import asyncpg
    conn = await asyncpg.connect(_u())
    try:
        for agency, name, value, disp, desc in ROWS:
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
                           CURRENT_DATE, 'RA-3E')""",
                agency, name,
                json.dumps({"type": "threshold", "value": value}),
                disp, desc, CITE,
            )
            print(f"  {agency}/{name} = {value} (inserted)")

        print("\n=== verify ===")
        for r in await conn.fetch(
            """SELECT guideline_name, guideline_value, citation
               FROM agency_guidelines
               WHERE guideline_name ILIKE 'income_mismatch%'
               AND valid_to IS NULL ORDER BY guideline_name"""
        ):
            print(f"  {r['guideline_name']}: {r['guideline_value']}  [{r['citation']}]")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())

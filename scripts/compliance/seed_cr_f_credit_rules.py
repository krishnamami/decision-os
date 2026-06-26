"""CR-F (RULE 8) — seed medical/non-medical collection + mortgage-late thresholds.

The CR-C credit framework already classifies these finding types, but the dollar
thresholds were prose NOTES and the conventional mortgage-late hard-block was a
hardcoded Python flag (`fannie_hard_block`). These rows make them catalogue-driven
(RULE 1). `medical_collection_excluded` already exists (RA — Fannie LL-2023-02) and
is skipped.

  medical_collection_ignore_amt                 = 2000  (Fannie B3-5.3-09, pre-2023 audit)
  non_medical_collection_loe_threshold          = 250   (Fannie B3-5.3-09)
  non_medical_collection_aggregate_payoff       = 1000  (Fannie B3-5.3-09)
  mortgage_late_30day_12mo_conventional_blocks  = true  (Fannie B3-5.3-01)

Idempotent; JSONB; agency layer, category 'credit'. Run:
  PYTHONIOENCODING=utf-8 PYTHONUTF8=1 python scripts/compliance/seed_cr_f_credit_rules.py
"""
import asyncio
import json
import os

from dotenv import load_dotenv

load_dotenv()

ROWS = [
    ("medical_collection_ignore_amt", 2000, "$2,000",
     "Medical collections at or below this per-tradeline amount are ignored "
     "(pre-2023 nuance; post-2023 medical collections are excluded entirely).",
     "Fannie Mae Selling Guide B3-5.3-09"),
    ("non_medical_collection_loe_threshold", 250, "$250",
     "A non-medical collection above this single-account balance requires a Letter "
     "of Explanation.", "Fannie Mae Selling Guide B3-5.3-09"),
    ("non_medical_collection_aggregate_payoff", 1000, "$1,000",
     "Non-medical collections whose aggregate balance exceeds this amount may require "
     "payoff.", "Fannie Mae Selling Guide B3-5.3-09"),
    ("mortgage_late_30day_12mo_conventional_blocks", True, "true",
     "A 30-day mortgage late in the last 12 months is a hard block for conventional "
     "financing.", "Fannie Mae Selling Guide B3-5.3-01"),
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
        print("-- seed agency_guidelines (CR-F collections + mortgage-late) --")
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
                   VALUES ('fannie','credit',$1,$2::jsonb,$3,$4,$5,
                           'https://selling-guide.fanniemae.com',
                           CURRENT_DATE, CURRENT_DATE, 'Accord compliance team',
                           CURRENT_DATE, 'CR-F')""",
                name, _gv(value), disp, desc, cite)
            print(f"  fannie/{name} = {value} (inserted)  [{cite}]")

        print("\n-- verify --")
        for r in await conn.fetch(
            """SELECT guideline_name, guideline_value, citation FROM agency_guidelines
               WHERE source_revision='CR-F' AND valid_to IS NULL ORDER BY guideline_name"""):
            print(f"  {r['guideline_name']}: {r['guideline_value']}  ({r['citation']})")
        total = await conn.fetchval(
            "SELECT COUNT(*) FROM agency_guidelines WHERE valid_to IS NULL AND is_active=true")
        print(f"\n  total active agency_guidelines: {total}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())

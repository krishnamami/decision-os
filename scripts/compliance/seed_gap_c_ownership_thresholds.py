"""
Gap (c) — seed the two SE business-ownership THRESHOLD rows that asset_resolver
gates on (biz_pct >= 100 / >= 50) so they are catalogue-driven, not Python
literals. The matching usable-credit FACTOR rows already exist (RA-SEED-C:
"Self-Employed Full Business Asset Credit"=100, "...Partial..."=50); only the
ownership cutoffs were missing.

  Self-Employed Business Ownership Sole Threshold      = 100  (Fannie B3-3.4-02)
  Self-Employed Business Ownership Majority Threshold  =  50  (Fannie B3-3.4-02)

These reproduce the existing hardcoded cutoffs exactly, so wiring asset_resolver
to read them is value-equivalent (16/16 holds). RULE 8: catalogue before code.

Idempotent (existence-checked; Type-2 history preserved). Catalogue rows only —
no resolver / persona / evidence-graph change here.

  python scripts/compliance/seed_gap_c_ownership_thresholds.py
"""
import asyncio
import json
import os
from dotenv import load_dotenv
load_dotenv()

# (agency, category, guideline_name, value, display, description, citation)
ROWS = [
    ("fannie", "asset", "Self-Employed Business Ownership Sole Threshold", 100,
     "100%",
     "A borrower with 100% ownership (sole proprietor) of a business qualifies "
     "for full business-asset credit toward reserves.",
     "Fannie Mae Selling Guide B3-3.4-02"),
    ("fannie", "asset", "Self-Employed Business Ownership Majority Threshold", 50,
     "50%",
     "A borrower with at least 50% (majority) ownership of a business qualifies "
     "for partial business-asset credit; below 50% business assets are not used.",
     "Fannie Mae Selling Guide B3-3.4-02"),
]


def _gv(value) -> str:
    """jsonb shape rule_loader understands (matches seed_pre_ra4f_rules)."""
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
        print("── seed agency_guidelines (Gap c — SE ownership thresholds) ──")
        for agency, cat, name, value, disp, desc, cite in ROWS:
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
                   VALUES ($1,$2,$3,$4::jsonb,$5,$6,$7,
                           'https://selling-guide.fanniemae.com',
                           CURRENT_DATE, CURRENT_DATE, 'Accord compliance team',
                           CURRENT_DATE, 'RA-GAP-C')""",
                agency, cat, name, _gv(value), disp, desc, cite,
            )
            print(f"  {agency}/{name} = {value} (inserted)  [{cite}]")

        print("\n── verify (Gap c rows) ──")
        for r in await conn.fetch(
            """SELECT guideline_name, guideline_value, agency, citation
               FROM agency_guidelines
               WHERE source_revision='RA-GAP-C' AND valid_to IS NULL
               ORDER BY guideline_name"""):
            print(f"  [{r['agency']:7}] {r['guideline_name']}: "
                  f"{r['guideline_value']}  [{r['citation']}]")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())

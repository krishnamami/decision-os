"""PL-B — seed the overlay-guardrail hard bounds into regulatory_rules (RULE 8).

`validate_overlay` historically hardcoded its bounds (FHA credit 580/500, DTI 57,
LTV 97). PL-B de-hardcodes it to read from the catalogue, so the federal-floor
layer must actually carry those values. This seeds the four missing rows.

Idempotent: regulatory_rules has no UNIQUE on rule_name (PK is rule_id), so we
check existence by rule_name and INSERT only when absent. Re-runnable; prints
what was seeded vs already present + the final count.

  python scripts/compliance/seed_pl_b_regulatory_floors.py
"""
import asyncio
import json
import os

from dotenv import load_dotenv

load_dotenv()

# rule_name -> (authority, category, value, display_value, description, citation)
FLOORS = {
    "credit_floor_fha_absolute_min": (
        "HUD", "credit", 500, "500",
        "FHA absolute minimum credit score (10% down payment required below 580).",
        "FHA HUD 4000.1"),
    "credit_floor_fha_standard_min": (
        "HUD", "credit", 580, "580",
        "FHA standard minimum credit score (3.5% down payment floor).",
        "FHA HUD 4000.1"),
    "dti_back_hard_max": (
        "FNMA", "dti", 57, "57%",
        "Absolute back-end DTI ceiling — no overlay may exceed this.",
        "Fannie Mae Selling Guide B3-6-02"),
    "ltv_hard_max": (
        "FNMA", "ltv", 97, "97%",
        "Absolute LTV ceiling for conventional purchase — no overlay may exceed this.",
        "Fannie Mae Selling Guide B2-1.2-01"),
}


def _dsn() -> str:
    return os.environ["DATABASE_URL"].replace("+asyncpg", "").replace("postgresql+psycopg2", "postgresql")


async def main():
    import asyncpg
    conn = await asyncpg.connect(_dsn())
    try:
        seeded, existed = [], []
        for name, (authority, category, value, display, desc, citation) in FLOORS.items():
            present = await conn.fetchval(
                "SELECT 1 FROM regulatory_rules WHERE rule_name=$1 LIMIT 1", name)
            if present:
                existed.append(name)
                continue
            await conn.execute(
                "INSERT INTO regulatory_rules "
                "(authority, category, rule_name, rule_value, display_value, description, citation, is_active) "
                "VALUES ($1,$2,$3,$4::jsonb,$5,$6,$7,true)",
                authority, category, name,
                json.dumps({"type": "threshold", "value": value, "operator": "floor_or_ceiling"}),
                display, desc, citation)
            seeded.append(name)

        total = await conn.fetchval("SELECT count(*) FROM regulatory_rules")
        print("PL-B regulatory floor seed:")
        print(f"  seeded ({len(seeded)}): {seeded}")
        print(f"  already present ({len(existed)}): {existed}")
        print(f"  regulatory_rules total now: {total}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())

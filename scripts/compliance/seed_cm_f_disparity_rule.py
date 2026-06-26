"""CM-F — seed the overlay-attributable disparity SCREEN into regulatory_rules (RULE 8).

This is an INTERNAL fair-lending screen, NOT a federal standard: a >20 percentage-
point gap in overlay-fail rate between a protected class and the reference group
flags the lender's overlay for review. The federal 4/5 ratio (0.80) is separate and
already seeded (CM-D). Idempotent.

  python scripts/compliance/seed_cm_f_disparity_rule.py
"""
import asyncio
import json
import os

from dotenv import load_dotenv

load_dotenv()

RULES = {
    "fair_lending_overlay_disparity_pct": (
        "Accord Internal", "fair_lending_internal_benchmark", 20, "20pp gap",
        "INTERNAL SCREEN ONLY (not a regulatory standard): a >20 percentage-point gap "
        "in overlay-fail rate between a protected class and the reference flags the "
        "overlay for fair-lending review. The federal EEOC 4/5 ratio (0.80) is the "
        "separate regulatory test.", "Internal screen (not regulatory)"),
}


def _dsn() -> str:
    return os.environ["DATABASE_URL"].replace("+asyncpg", "").replace("postgresql+psycopg2", "postgresql")


async def main():
    import asyncpg
    conn = await asyncpg.connect(_dsn())
    try:
        seeded, existed = [], []
        for name, (authority, category, value, display, desc, citation) in RULES.items():
            if await conn.fetchval("SELECT 1 FROM regulatory_rules WHERE rule_name=$1 LIMIT 1", name):
                existed.append(name)
                continue
            await conn.execute(
                "INSERT INTO regulatory_rules "
                "(authority, category, rule_name, rule_value, display_value, description, citation, is_active) "
                "VALUES ($1,$2,$3,$4::jsonb,$5,$6,$7,true)",
                authority, category, name,
                json.dumps({"type": "threshold", "value": value, "unit": "percentage_points"}),
                display, desc, citation)
            seeded.append(name)
        total = await conn.fetchval("SELECT count(*) FROM regulatory_rules")
        print(f"CM-F seed: seeded={seeded} existed={existed} regulatory_rules total={total}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())

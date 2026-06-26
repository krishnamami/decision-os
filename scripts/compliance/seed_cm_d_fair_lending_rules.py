"""CM-D (RULE 8) — seed fair-lending thresholds into regulatory_rules.

These are EEOC/CFPB REGULATORY standards (federal floor), not Fannie/agency
guidelines — so they live in regulatory_rules, not agency_guidelines.

  fair_lending_four_fifths_ratio = 0.80  (EEOC Uniform Guidelines 29 CFR 1607.4(D);
                                          mirrored by HUD/CFPB for lending)
  fair_lending_min_sample_size   = 30    (CFPB HMDA examination sampling adequacy)

Idempotent; JSONB rule_value; authority 'cfpb', category 'fair_lending'. Run:
  PYTHONIOENCODING=utf-8 PYTHONUTF8=1 python scripts/compliance/seed_cm_d_fair_lending_rules.py
"""
import asyncio
import json
import os

from dotenv import load_dotenv

load_dotenv()

ROWS = [
    ("fair_lending_four_fifths_ratio", 0.80, "0.80",
     "Four-fifths (80%) rule: a group's selection rate below 80% of the highest "
     "group's rate is prima-facie disparate impact.",
     "EEOC Uniform Guidelines 29 CFR 1607.4(D) + ECOA 12 CFR 202"),
    ("fair_lending_min_sample_size", 30, "30",
     "Minimum sample size for a statistically meaningful disparate-impact analysis.",
     "CFPB HMDA Examination Procedures"),
]


def _gv(value) -> str:
    return json.dumps({"type": "threshold", "value": value})


def _u():
    return os.environ["DATABASE_URL"].replace("+asyncpg", "").replace(
        "postgresql+psycopg2", "postgresql")


async def main():
    import asyncpg
    conn = await asyncpg.connect(_u())
    try:
        print("-- seed regulatory_rules (CM-D fair-lending thresholds) --")
        for name, value, disp, desc, cite in ROWS:
            exists = await conn.fetchval(
                "SELECT 1 FROM regulatory_rules WHERE rule_name=$1 AND is_active=true LIMIT 1",
                name)
            if exists:
                print(f"  cfpb/{name}: already present, skipping")
                continue
            await conn.execute(
                """INSERT INTO regulatory_rules
                   (authority, category, rule_name, rule_value, display_value,
                    description, citation, effective_date, is_active)
                   VALUES ('cfpb','fair_lending',$1,$2::jsonb,$3,$4,$5,CURRENT_DATE,true)""",
                name, _gv(value), disp, desc, cite)
            print(f"  cfpb/{name} = {value} (inserted)  [{cite}]")

        print("\n-- verify --")
        for r in await conn.fetch(
            """SELECT rule_name, rule_value, citation FROM regulatory_rules
               WHERE category='fair_lending' AND is_active=true ORDER BY rule_name"""):
            print(f"  {r['rule_name']}: {r['rule_value']}  ({r['citation']})")
        print(f"\n  regulatory_rules total: {await conn.fetchval('SELECT COUNT(*) FROM regulatory_rules')}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())

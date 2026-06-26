"""FR-F (RULE 8) — seed VA residual-income estimate parameters into regulatory_rules.

The VA residual TABLE itself (region x family size) is a fixed regulatory reference
table hosted as a code constant (VA_RESIDUAL_TABLE) — like the LLPA grid / county
limits. Only the tunable/estimate scalars are seeded here (federal VA standards):

  va_residual_maintenance_per_sqft_monthly = 0.14  (VA Pamphlet 26-7 Ch.4 — maint+utilities)
  va_residual_tax_estimate_pct             = 25     (heuristic when taxes not extracted)
  va_residual_min_loan_amount              = 80000  (table applies at >= $80k)

Idempotent; JSONB; authority 'va', category 'residual_income'. Run:
  PYTHONIOENCODING=utf-8 PYTHONUTF8=1 python scripts/compliance/seed_fr_f_va_residual_rules.py
"""
import asyncio
import json
import os

from dotenv import load_dotenv

load_dotenv()

_CITE = "VA Pamphlet 26-7 Chapter 4"
ROWS = [
    ("va_residual_maintenance_per_sqft_monthly", 0.14, "$0.14/sqft/mo",
     "Monthly maintenance + utilities estimate per square foot for VA residual income."),
    ("va_residual_tax_estimate_pct", 25, "25%",
     "Estimated annual tax+withholding rate applied to gross income when actual taxes "
     "are not extracted (VA residual income heuristic)."),
    ("va_residual_min_loan_amount", 80000, "$80,000",
     "The VA residual-income table applies to loan amounts at or above this threshold."),
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
        print("-- seed regulatory_rules (FR-F VA residual scalars) --")
        for name, value, disp, desc in ROWS:
            exists = await conn.fetchval(
                "SELECT 1 FROM regulatory_rules WHERE rule_name=$1 AND is_active=true LIMIT 1",
                name)
            if exists:
                print(f"  va/{name}: already present, skipping")
                continue
            await conn.execute(
                """INSERT INTO regulatory_rules
                   (authority, category, rule_name, rule_value, display_value,
                    description, citation, effective_date, is_active)
                   VALUES ('va','residual_income',$1,$2::jsonb,$3,$4,$5,CURRENT_DATE,true)""",
                name, _gv(value), disp, desc, _CITE)
            print(f"  va/{name} = {value} (inserted)  [{_CITE}]")

        print("\n-- verify --")
        for r in await conn.fetch(
            """SELECT rule_name, rule_value, citation FROM regulatory_rules
               WHERE category='residual_income' AND is_active=true ORDER BY rule_name"""):
            print(f"  {r['rule_name']}: {r['rule_value']}  ({r['citation']})")
        print(f"\n  regulatory_rules total: {await conn.fetchval('SELECT COUNT(*) FROM regulatory_rules')}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())

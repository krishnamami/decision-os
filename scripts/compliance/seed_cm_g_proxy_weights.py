"""CM-G — seed proxy-discrimination risk heuristics into regulatory_rules (RULE 8).

These are INTERNAL screening heuristics informed by CFPB supervisory research —
NOT regulatory standards or legal determinations of discrimination. Every row's
description says so. Idempotent.

  python scripts/compliance/seed_cm_g_proxy_weights.py
"""
import asyncio
import json
import os

from dotenv import load_dotenv

load_dotenv()

_NOTE = "Internal proxy-risk heuristic (non-regulatory) — informed by CFPB research."
RULES = {
    "credit_floor_proxy_risk_weight": (
        0.70, "0.70", f"{_NOTE} Credit score has a known correlation with race/ethnicity."),
    "dti_proxy_risk_weight": (
        0.45, "0.45", f"{_NOTE} DTI correlates with income, which correlates with race (moderate)."),
    "ltv_proxy_risk_weight": (
        0.35, "0.35", f"{_NOTE} LTV correlates with property value/geography (lower but present)."),
    "overlay_bias_elevated_threshold": (
        0.55, "0.55", f"{_NOTE} Composite proxy-risk score above this -> 'elevated'."),
    "overlay_bias_high_threshold": (
        0.75, "0.75", f"{_NOTE} Composite proxy-risk score above this -> 'high'."),
}


def _dsn() -> str:
    return os.environ["DATABASE_URL"].replace("+asyncpg", "").replace("postgresql+psycopg2", "postgresql")


async def main():
    import asyncpg
    conn = await asyncpg.connect(_dsn())
    try:
        seeded, existed = [], []
        for name, (value, display, desc) in RULES.items():
            if await conn.fetchval("SELECT 1 FROM regulatory_rules WHERE rule_name=$1 LIMIT 1", name):
                existed.append(name)
                continue
            await conn.execute(
                "INSERT INTO regulatory_rules "
                "(authority, category, rule_name, rule_value, display_value, description, citation, is_active) "
                "VALUES ($1,$2,$3,$4::jsonb,$5,$6,$7,true)",
                "Accord Internal", "fair_lending_internal_benchmark", name,
                json.dumps({"type": "weight", "value": value}), display, desc,
                "CFPB Fair Lending Supervisory Research (internal heuristic)")
            seeded.append(name)
        total = await conn.fetchval("SELECT count(*) FROM regulatory_rules")
        print(f"CM-G seed: seeded={seeded} existed={existed} regulatory_rules total={total}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())

"""CF-C — seed CRA assessment thresholds into regulatory_rules (RULE 8). Idempotent.

Two kinds, clearly distinguished:
  FEDERAL (real, 12 CFR 25/228) — the census-tract income-tier cutoffs (% of AMI).
  INTERNAL BENCHMARK (NOT regulatory) — the LMI-ratio -> self-assessment rating
    thresholds. Official CRA ratings are examiner-assigned; these are an internal
    benchmark only, and each row's description says so explicitly.

  python scripts/compliance/seed_cf_c_cra_rules.py
"""
import asyncio
import json
import os

from dotenv import load_dotenv

load_dotenv()

# rule_name -> (authority, category, value, display, description, citation)
RULES = {
    # ── Federal AMI tier cutoffs (12 CFR 25/228) ──
    "cra_lmi_low_max_pct": (
        "FFIEC", "cra", 50, "<50% AMI",
        "Census tract income tier 'low': tract median income below 50% of Area "
        "Median Income.", "12 CFR 25 / 228 (CRA)"),
    "cra_moderate_max_pct": (
        "FFIEC", "cra", 80, "50-79.9% AMI",
        "Census tract income tier 'moderate': 50-79.9% of Area Median Income.",
        "12 CFR 25 / 228 (CRA)"),
    "cra_middle_max_pct": (
        "FFIEC", "cra", 120, "80-119.9% AMI",
        "Census tract income tier 'middle': 80-119.9% of AMI; 'upper' is >=120%.",
        "12 CFR 25 / 228 (CRA)"),
    # ── Internal self-assessment benchmark (NOT a regulatory CRA rating) ──
    "cra_lmi_ratio_outstanding_pct": (
        "Accord Internal", "cra_internal_benchmark", 40, "40% LMI",
        "INTERNAL BENCHMARK ONLY (not a regulatory CRA rating): LMI lending ratio "
        ">= 40% -> 'outstanding' self-assessment. Official CRA ratings are assigned "
        "by federal examiners.", "Internal benchmark (not regulatory)"),
    "cra_lmi_ratio_satisfactory_pct": (
        "Accord Internal", "cra_internal_benchmark", 25, "25% LMI",
        "INTERNAL BENCHMARK ONLY: LMI ratio >= 25% -> 'satisfactory' self-assessment.",
        "Internal benchmark (not regulatory)"),
    "cra_lmi_ratio_needs_improvement_pct": (
        "Accord Internal", "cra_internal_benchmark", 10, "10% LMI",
        "INTERNAL BENCHMARK ONLY: LMI ratio >= 10% -> 'needs_to_improve'; below -> "
        "'substantial_noncompliance' self-assessment.", "Internal benchmark (not regulatory)"),
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
                json.dumps({"type": "threshold", "value": value, "unit": "percent"}),
                display, desc, citation)
            seeded.append(name)
        total = await conn.fetchval("SELECT count(*) FROM regulatory_rules")
        print("CF-C CRA rule seed:")
        print(f"  seeded ({len(seeded)}): {seeded}")
        print(f"  already present ({len(existed)}): {existed}")
        print(f"  regulatory_rules total: {total}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())

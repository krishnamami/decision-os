"""CM-E — seed state-specific mortgage rules into regulatory_rules.state_code (RULE 8).

Two operations, both idempotent and 16/16-safe (verified: meridian loans carry no
property_state, and vw_compliance_check_context does NOT join regulatory_rules — it
reads a stored verifications flag — so neither insert nor enrich touches the live
compliance path or the meridian scenarios):

  1. INSERT 6 genuinely-new state rules (NY anti-flip, MA, NJ, CA, IL, MN).
  2. ENRICH 4 EXISTING threshold rows (TX cash-out, NY usury, GA, NC) with a
     `field` key in their rule_value JSONB so StateRuleResolver can evaluate them
     (they carried operator+value but no field). Additive merge — value/operator
     preserved; get_rule (_parse reads `value`) + vw_regulation_transparency
     (reads display_value/citation) are unaffected.

  python scripts/compliance/seed_cm_e_state_rules.py
"""
import asyncio
import json
import os

from dotenv import load_dotenv

load_dotenv()

# New rows: rule_name -> (state, authority, category, rule_value, display_value, desc, citation)
NEW_RULES = {
    "anti_flipping_min_ownership_months": (
        "NY", "NY DFS", "underwriting",
        {"type": "threshold", "operator": "min", "field": "months_owned", "value": 12, "unit": "months"},
        "12 months", "Refinance requires 12 months prior ownership (anti-flipping).",
        "NY RPAPL 1304"),
    "high_cost_income_doc_required": (
        "MA", "MA Division of Banks", "predatory",
        {"type": "requirement", "value": "full_income_docs_required_high_cost"},
        "required", "High-cost home loans require full income documentation.",
        "MA Predatory Home Loan Practices 209 CMR 32 / 940 CMR 8"),
    "high_cost_loan_points_fee_pct_max": (
        "NJ", "NJ Dept. of Banking", "predatory",
        {"type": "threshold", "operator": "max", "field": "points_fees_pct", "value": 6, "unit": "percent"},
        "6% max", "Home-equity loan points + fees capped at 6% of loan amount (HOSA).",
        "NJ HOSA N.J.S.A. 46:10B-22"),
    "hpml_prepayment_penalty_prohibited": (
        "CA", "CA DFPI", "predatory",
        {"type": "prohibition", "value": "prepayment_penalty_prohibited_hpml"},
        "prohibited", "Higher-priced mortgage loans may not carry a prepayment penalty.",
        "CA Fin. Code §4970 et seq."),
    "high_cost_threshold_rate_spread": (
        "IL", "IL DFPR", "predatory",
        {"type": "threshold", "operator": "max", "field": "rate_spread_pct", "value": 6, "unit": "percent"},
        "6% max", "High-cost rate spread over APOR capped at 6%.",
        "IL High Risk Home Loan Act 815 ILCS 137"),
    "foreclosure_prevention_counseling_required": (
        "MN", "MN Dept. of Commerce", "foreclosure",
        {"type": "requirement", "value": "foreclosure_prevention_counseling_required"},
        "required", "Pre-foreclosure counseling required for certain residential loans.",
        "MN Stat. §58A.14"),
}

# Existing threshold rows -> the entity field they gate (added to rule_value).
ENRICH_FIELD = {
    "Texas Cash-Out Refinance LTV": "ltv",
    "New York Usury Cap": "note_rate_pct",
    "Georgia Fair Lending High-Cost Threshold": "points_fees_pct",
    "North Carolina High-Cost Rate Spread": "rate_spread_pct",
}


def _dsn() -> str:
    return os.environ["DATABASE_URL"].replace("+asyncpg", "").replace("postgresql+psycopg2", "postgresql")


async def main():
    import asyncpg
    conn = await asyncpg.connect(_dsn())
    try:
        seeded, existed = [], []
        for name, (state, authority, category, rv, display, desc, citation) in NEW_RULES.items():
            present = await conn.fetchval(
                "SELECT 1 FROM regulatory_rules WHERE rule_name=$1 LIMIT 1", name)
            if present:
                existed.append(name)
                continue
            await conn.execute(
                "INSERT INTO regulatory_rules "
                "(authority, state_code, category, rule_name, rule_value, display_value, description, citation, is_active) "
                "VALUES ($1,$2,$3,$4,$5::jsonb,$6,$7,$8,true)",
                authority, state, category, name, json.dumps(rv), display, desc, citation)
            seeded.append(f"[{state}] {name}")

        enriched, missing = [], []
        for rule_name, field in ENRICH_FIELD.items():
            row = await conn.fetchrow(
                "SELECT rule_value FROM regulatory_rules WHERE rule_name=$1 LIMIT 1", rule_name)
            if not row:
                missing.append(rule_name)
                continue
            rv = row["rule_value"]
            if isinstance(rv, str):
                rv = json.loads(rv)
            if rv.get("field") == field:
                enriched.append(f"{rule_name} (already had field)")
                continue
            rv["field"] = field
            await conn.execute(
                "UPDATE regulatory_rules SET rule_value=$2::jsonb WHERE rule_name=$1",
                rule_name, json.dumps(rv))
            enriched.append(f"{rule_name} -> field={field}")

        total = await conn.fetchval("SELECT count(*) FROM regulatory_rules")
        state_total = await conn.fetchval(
            "SELECT count(*) FROM regulatory_rules WHERE state_code IS NOT NULL")
        states = await conn.fetch(
            "SELECT DISTINCT state_code FROM regulatory_rules WHERE state_code IS NOT NULL ORDER BY state_code")
        print("CM-E state-rule seed:")
        print(f"  inserted ({len(seeded)}): {seeded}")
        print(f"  already present ({len(existed)}): {existed}")
        print(f"  enriched with field ({len(enriched)}): {enriched}")
        if missing:
            print(f"  enrich target MISSING: {missing}")
        print(f"  regulatory_rules total: {total} | state-tagged: {state_total}")
        print(f"  states covered: {[r['state_code'] for r in states]}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())

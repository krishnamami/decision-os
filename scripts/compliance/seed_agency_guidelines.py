"""Seed the agency guideline layer (📋 Fannie/Freddie/FHA/VA — preset, monitored).

  python scripts/compliance/seed_agency_guidelines.py

Idempotent: clears agency_guidelines and re-inserts the canonical set.
"""

import asyncio
import json
import os
from datetime import date

from dotenv import load_dotenv

load_dotenv()

# (agency, category, name, value, display, description, conditions, citation, source_url, effective_date, verified_by)
ROWS = [
    # ── Fannie Mae ──
    ("fannie", "credit", "Minimum Credit Score",
     {"type": "threshold", "value": 620, "operator": "min"}, "620",
     "Minimum representative credit score for conventional loans", None,
     "Selling Guide B3-5.1-01", "https://selling-guide.fanniemae.com", "2026-06-01", "Accord compliance team"),
    ("fannie", "dti", "Manual UW Maximum DTI",
     {"type": "threshold", "value": 36, "operator": "max"}, "36%",
     "Maximum DTI for manually underwritten loans", "45% with documented compensating factors",
     "Selling Guide B3-6-02", None, "2026-06-01", "Accord compliance team"),
    ("fannie", "dti", "DU Maximum DTI",
     {"type": "threshold", "value": 50, "operator": "max"}, "50%",
     "Maximum DTI with DU Approve/Eligible recommendation",
     "Requires DU approval and strong compensating factors including 12+ months reserves or residual income ≥ $2,500/mo",
     "Selling Guide B3-6-02", None, "2026-06-01", "Accord compliance team"),
    ("fannie", "ltv", "Primary Residence 1-Unit Max LTV",
     {"type": "threshold", "value": 97, "operator": "max"}, "97%",
     "Maximum LTV for primary residence purchase, 1 unit", None,
     "Selling Guide B2-1.2-01", None, "2026-06-01", "Accord compliance team"),
    ("fannie", "ltv", "Investment Property Max LTV",
     {"type": "threshold", "value": 85, "operator": "max"}, "85%",
     "Maximum LTV for investment property purchase", None,
     "Selling Guide B2-1.2-01", None, "2026-06-01", "Accord compliance team"),
    ("fannie", "reserves", "Investment Property Reserves",
     {"type": "threshold", "value": 6, "operator": "min", "unit": "months"}, "6 months",
     "Minimum reserves for investment property", None,
     "Selling Guide B3-4.1-01", None, "2026-06-01", "Accord compliance team"),
    ("fannie", "product", "2026 Conforming Loan Limit",
     {"type": "threshold", "value": 766550, "operator": "max"}, "$766,550",
     "2026 baseline conforming loan limit (1-unit)", "High-cost areas up to $1,149,825",
     "FHFA 2026 Announcement", "https://www.fhfa.gov", "2026-01-01", "Automated download"),
    # ── FHA ──
    ("fha", "credit", "FHA Minimum Score (3.5% down)",
     {"type": "threshold", "value": 580, "operator": "min"}, "580",
     "Minimum credit score for FHA with 3.5% down payment", "Score 500-579 requires 10% down payment",
     "HUD Handbook 4000.1 II.A.5.c", None, "2026-06-01", "Accord compliance team"),
    ("fha", "dti", "FHA Maximum DTI",
     {"type": "threshold", "value": 43, "operator": "max"}, "43%",
     "Maximum DTI for manually underwritten FHA loans", "Up to 57% with AUS approval and compensating factors",
     "HUD Handbook 4000.1 II.A.5.d", None, "2026-06-01", "Accord compliance team"),
    ("fha", "ltv", "FHA Maximum LTV (Purchase)",
     {"type": "threshold", "value": 96.5, "operator": "max"}, "96.5%",
     "Maximum LTV for FHA purchase loans", None,
     "HUD Handbook 4000.1 II.A.2", None, "2026-06-01", "Accord compliance team"),
    ("fha", "mi", "FHA Annual MIP Rate",
     {"type": "threshold", "value": 0.85, "unit": "percent_annual"}, "0.85%",
     "Annual MIP for loans >15yr, >95% LTV", "0.80% for ≤95% LTV. 1.75% upfront MIP on all FHA loans.",
     "HUD Mortgagee Letter 2023-05", None, "2026-06-01", "Accord compliance team"),
    # ── VA ──
    ("va", "ltv", "VA Maximum LTV",
     {"type": "threshold", "value": 100, "operator": "max"}, "100%",
     "VA allows 100% financing (no down payment required)", None,
     "VA Lender's Handbook Ch. 4", None, "2026-06-01", "Accord compliance team"),
    ("va", "fee", "VA Funding Fee (First Use)",
     {"type": "threshold", "value": 2.15, "unit": "percent"}, "2.15%",
     "Funding fee for first-time VA loan use (0% down)", "3.3% for subsequent use. Exempt for disabled veterans.",
     "VA Circular 26-22-1", None, "2026-06-01", "Accord compliance team"),
    # ── Freddie Mac (parity with Fannie for the conventional program) ──
    ("freddie", "credit", "Minimum Indicator Score",
     {"type": "threshold", "value": 620, "operator": "min"}, "620",
     "Minimum indicator score for conventional loans", None,
     "Single-Family Seller/Servicer Guide 5203.2", "https://guide.freddiemac.com", "2026-06-01", "Accord compliance team"),
    ("freddie", "ltv", "Home Possible Max LTV",
     {"type": "threshold", "value": 97, "operator": "max"}, "97%",
     "Maximum LTV for Home Possible primary residence purchase", None,
     "Guide 4501.10", None, "2026-06-01", "Accord compliance team"),
]


async def main() -> None:
    import asyncpg

    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL not set")
    conn = await asyncpg.connect(url)
    try:
        async with conn.transaction():
            await conn.execute("DELETE FROM agency_guidelines")
            for agency, cat, name, val, disp, desc, cond, cite, url2, eff, verifier in ROWS:
                await conn.execute(
                    "INSERT INTO agency_guidelines "
                    "(agency, category, guideline_name, guideline_value, display_value, description, conditions, "
                    " citation, source_url, effective_date, last_verified, verified_by) "
                    "VALUES ($1,$2,$3,$4::jsonb,$5,$6,$7,$8,$9,$10,$10,$11)",
                    agency, cat, name, json.dumps(val), disp, desc, cond, cite, url2,
                    date.fromisoformat(eff) if eff else None, verifier,
                )
        n = await conn.fetchval("SELECT count(*) FROM agency_guidelines")
        print(f"Seeded agency_guidelines: {n} rows")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())

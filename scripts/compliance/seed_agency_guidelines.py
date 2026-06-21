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

    # ── Preserved: pricing/LTV/MI rows that were live in agency_guidelines
    #    but absent from this seeder. Kept verbatim (source_url None matches
    #    their sibling rows) so the DELETE+reinsert is non-destructive. ──
    ("fannie", "ltv", "ltv_max_cashout",
     {"type": "threshold", "value": 80, "operator": "max", "loan_purpose": "cash_out"}, "80%",
     "Maximum LTV for a cash-out refinance, primary residence 1-unit.", None,
     "Selling Guide B2-1.3-03", None, "2026-06-01", "Accord compliance team"),
    ("fannie", "ltv", "ltv_max_refi_rateterm",
     {"type": "threshold", "value": 95, "operator": "max", "loan_purpose": "rate_term_refinance"}, "95%",
     "Maximum LTV for a rate/term (limited cash-out) refinance, primary residence 1-unit.", None,
     "Selling Guide B2-1.3-02", None, "2026-06-01", "Accord compliance team"),
    ("fannie", "mi", "mi_required_above_ltv",
     {"type": "threshold", "unit": "ltv_percent", "value": 80, "operator": "above"}, "MI required when LTV > 80%",
     "Borrower-paid mortgage insurance is required on conventional loans when LTV exceeds 80%; cancellable per HPA.", None,
     "Selling Guide B7-1-01", None, "2026-06-01", "Accord compliance team"),
    ("fha", "dti", "dti_back_max_aus",
     {"type": "threshold", "value": 57, "operator": "max"}, "57%",
     "Maximum back-end DTI for FHA with TOTAL Scorecard / AUS approval and compensating factors.",
     "Requires AUS approval; manual-underwrite cap is lower (43% base).",
     "HUD Handbook 4000.1 II.A.5.d", None, "2026-06-01", "Accord compliance team"),
    ("fha", "mi", "mip_annual_lt95_30yr",
     {"type": "threshold", "unit": "percent_annual", "value": 0.80}, "0.80%",
     "Annual MIP rate for 30-year FHA loans with LTV at or below 95%.",
     "Loans with LTV > 95% are 0.85% annual MIP.",
     "HUD Mortgagee Letter 2023-05", None, "2026-06-01", "Accord compliance team"),
    ("fha", "mi", "mip_upfront_pct",
     {"type": "threshold", "unit": "percent_upfront", "value": 1.75}, "1.75%",
     "Upfront Mortgage Insurance Premium (UFMIP) charged on all FHA loans.", None,
     "HUD Mortgagee Letter 2023-05", None, "2026-06-01", "Accord compliance team"),
    ("va", "dti", "dti_back_guideline",
     {"type": "guideline", "value": 41, "operator": "max"}, "41%",
     "VA back-end DTI guideline (not a hard cap); loans above 41% are allowed with sufficient residual income.",
     "Soft guideline — exceedable with residual-income compensating factors.",
     "VA Lender's Handbook Ch. 4", None, "2026-06-01", "Accord compliance team"),

    # ── Asset — Fannie Mae B3-4.3-04 ──
    ("fannie", "asset", "qualifying_factor_checking",
     {"type": "factor", "value": 1.00}, "1.00",
     "Qualifying factor for checking accounts — 100% of balance counts.", None,
     "Fannie Mae B3-4.3-04", "https://selling-guide.fanniemae.com/sel/b3/4.3/04", "2026-06-01", "Accord compliance team"),
    ("fannie", "asset", "qualifying_factor_savings",
     {"type": "factor", "value": 1.00}, "1.00",
     "Qualifying factor for savings accounts — 100% of balance counts.", None,
     "Fannie Mae B3-4.3-04", "https://selling-guide.fanniemae.com/sel/b3/4.3/04", "2026-06-01", "Accord compliance team"),
    ("fannie", "asset", "qualifying_factor_cd",
     {"type": "factor", "value": 1.00}, "1.00",
     "Qualifying factor for certificates of deposit — 100% of balance counts.", None,
     "Fannie Mae B3-4.3-04", "https://selling-guide.fanniemae.com/sel/b3/4.3/04", "2026-06-01", "Accord compliance team"),
    ("fannie", "asset", "qualifying_factor_retirement",
     {"type": "factor", "value": 0.60}, "0.60",
     "Qualifying factor for retirement accounts — 60% of vested balance.", None,
     "Fannie Mae B3-4.3-04", "https://selling-guide.fanniemae.com/sel/b3/4.3/04", "2026-06-01", "Accord compliance team"),
    ("fannie", "asset", "qualifying_factor_stocks_bonds",
     {"type": "factor", "value": 0.70}, "0.70",
     "Qualifying factor for stocks and bonds — 70% of value.", None,
     "Fannie Mae B3-4.3-04", "https://selling-guide.fanniemae.com/sel/b3/4.3/04", "2026-06-01", "Accord compliance team"),
    ("fannie", "asset", "qualifying_factor_crypto",
     {"type": "factor", "value": 0.00}, "0.00",
     "Qualifying factor for cryptocurrency — excluded from qualifying assets.", None,
     "Fannie Mae B3-4.3-04", "https://selling-guide.fanniemae.com/sel/b3/4.3/04", "2026-06-01", "Accord compliance team"),
    ("fannie", "asset", "minimum_reserves_months",
     {"type": "threshold", "value": 2, "unit": "months", "operator": "min"}, "2 months",
     "Minimum reserves (months of PITIA) for primary residence purchase.", None,
     "Fannie Mae B3-4.3-04", "https://selling-guide.fanniemae.com/sel/b3/4.3/04", "2026-06-01", "Accord compliance team"),
    ("fannie", "asset", "large_deposit_threshold_pct",
     {"type": "threshold", "value": 50, "unit": "percent"}, "50%",
     "A deposit exceeding 50% of qualifying monthly income requires sourcing.", None,
     "Fannie Mae B3-4.3-04", "https://selling-guide.fanniemae.com/sel/b3/4.3/04", "2026-06-01", "Accord compliance team"),
    ("fannie", "asset", "seasoning_days_required",
     {"type": "threshold", "value": 60, "unit": "days", "operator": "min"}, "60 days",
     "Account funds must show 60 days of history (statements) to be seasoned.", None,
     "Fannie Mae B3-4.3-04", "https://selling-guide.fanniemae.com/sel/b3/4.3/04", "2026-06-01", "Accord compliance team"),

    # ── Credit waiting periods — one row per agency per event type.
    #    Fannie reference B3-5.3-07; FHA/VA cite their own handbooks. ──
    ("fannie", "credit", "bankruptcy_ch7_waiting_years",
     {"type": "threshold", "value": 4, "unit": "years"}, "4 years",
     "Chapter 7 bankruptcy waiting period from discharge.", "2 years with documented extenuating circumstances.",
     "Fannie Mae B3-5.3-07", "https://selling-guide.fanniemae.com/sel/b3/5.3/07", "2026-06-01", "Accord compliance team"),
    ("fha", "credit", "bankruptcy_ch7_waiting_years",
     {"type": "threshold", "value": 2, "unit": "years"}, "2 years",
     "Chapter 7 bankruptcy waiting period from discharge.", None,
     "HUD Handbook 4000.1 II.A.5", "https://www.hud.gov/program_offices/administration/hudclips/handbooks/hsgh", "2026-06-01", "Accord compliance team"),
    ("va", "credit", "bankruptcy_ch7_waiting_years",
     {"type": "threshold", "value": 2, "unit": "years"}, "2 years",
     "Chapter 7 bankruptcy waiting period from discharge.", None,
     "VA Lender's Handbook Ch. 4", "https://www.benefits.va.gov/warms/pam26_7.asp", "2026-06-01", "Accord compliance team"),
    ("fannie", "credit", "bankruptcy_ch13_waiting_years",
     {"type": "threshold", "value": 2, "unit": "years"}, "2 years",
     "Chapter 13 bankruptcy waiting period from discharge.", "4 years from dismissal.",
     "Fannie Mae B3-5.3-07", "https://selling-guide.fanniemae.com/sel/b3/5.3/07", "2026-06-01", "Accord compliance team"),
    ("fha", "credit", "bankruptcy_ch13_waiting_years",
     {"type": "threshold", "value": 1, "unit": "years"}, "1 year",
     "Chapter 13 — 1 year of satisfactory payments with court approval.", None,
     "HUD Handbook 4000.1 II.A.5", "https://www.hud.gov/program_offices/administration/hudclips/handbooks/hsgh", "2026-06-01", "Accord compliance team"),
    ("va", "credit", "bankruptcy_ch13_waiting_years",
     {"type": "threshold", "value": 1, "unit": "years"}, "1 year",
     "Chapter 13 — 1 year of satisfactory payments.", None,
     "VA Lender's Handbook Ch. 4", "https://www.benefits.va.gov/warms/pam26_7.asp", "2026-06-01", "Accord compliance team"),
    ("fannie", "credit", "foreclosure_waiting_years",
     {"type": "threshold", "value": 7, "unit": "years"}, "7 years",
     "Foreclosure waiting period from completion date.", "3 years with extenuating circumstances.",
     "Fannie Mae B3-5.3-07", "https://selling-guide.fanniemae.com/sel/b3/5.3/07", "2026-06-01", "Accord compliance team"),
    ("fha", "credit", "foreclosure_waiting_years",
     {"type": "threshold", "value": 3, "unit": "years"}, "3 years",
     "Foreclosure waiting period from completion date.", None,
     "HUD Handbook 4000.1 II.A.5", "https://www.hud.gov/program_offices/administration/hudclips/handbooks/hsgh", "2026-06-01", "Accord compliance team"),
    ("va", "credit", "foreclosure_waiting_years",
     {"type": "threshold", "value": 2, "unit": "years"}, "2 years",
     "Foreclosure waiting period from completion date.", None,
     "VA Lender's Handbook Ch. 4", "https://www.benefits.va.gov/warms/pam26_7.asp", "2026-06-01", "Accord compliance team"),
    ("fannie", "credit", "short_sale_waiting_years",
     {"type": "threshold", "value": 4, "unit": "years"}, "4 years",
     "Short sale waiting period from completion date.", None,
     "Fannie Mae B3-5.3-07", "https://selling-guide.fanniemae.com/sel/b3/5.3/07", "2026-06-01", "Accord compliance team"),
    ("fha", "credit", "short_sale_waiting_years",
     {"type": "threshold", "value": 3, "unit": "years"}, "3 years",
     "Short sale waiting period from completion date.", None,
     "HUD Handbook 4000.1 II.A.5", "https://www.hud.gov/program_offices/administration/hudclips/handbooks/hsgh", "2026-06-01", "Accord compliance team"),
    ("va", "credit", "short_sale_waiting_years",
     {"type": "threshold", "value": 2, "unit": "years"}, "2 years",
     "Short sale waiting period from completion date.", None,
     "VA Lender's Handbook Ch. 4", "https://www.benefits.va.gov/warms/pam26_7.asp", "2026-06-01", "Accord compliance team"),
    ("fannie", "credit", "deed_in_lieu_waiting_years",
     {"type": "threshold", "value": 4, "unit": "years"}, "4 years",
     "Deed-in-lieu waiting period from completion date.", None,
     "Fannie Mae B3-5.3-07", "https://selling-guide.fanniemae.com/sel/b3/5.3/07", "2026-06-01", "Accord compliance team"),
    ("fha", "credit", "deed_in_lieu_waiting_years",
     {"type": "threshold", "value": 3, "unit": "years"}, "3 years",
     "Deed-in-lieu waiting period from completion date.", None,
     "HUD Handbook 4000.1 II.A.5", "https://www.hud.gov/program_offices/administration/hudclips/handbooks/hsgh", "2026-06-01", "Accord compliance team"),
    ("va", "credit", "deed_in_lieu_waiting_years",
     {"type": "threshold", "value": 2, "unit": "years"}, "2 years",
     "Deed-in-lieu waiting period from completion date.", None,
     "VA Lender's Handbook Ch. 4", "https://www.benefits.va.gov/warms/pam26_7.asp", "2026-06-01", "Accord compliance team"),

    # ── Income ──
    ("fannie", "income", "student_loan_deferred_rate_pct",
     {"type": "factor", "value": 1.0, "unit": "percent"}, "1.0%",
     "Deferred student loans: use 1% of the outstanding balance as the monthly payment.", None,
     "Fannie Mae B3-6-05", "https://selling-guide.fanniemae.com/sel/b3/6/05", "2026-06-01", "Accord compliance team"),
    ("fannie", "income", "medical_collection_excluded",
     {"type": "boolean", "value": True}, "excluded",
     "Medical collection accounts are excluded from the credit/DTI analysis.", None,
     "Fannie Mae LL-2023-02", "https://singlefamily.fanniemae.com/media/28526/display", "2026-06-01", "Accord compliance team"),
    ("fannie", "income", "rental_vacancy_factor_pct",
     {"type": "threshold", "value": 25, "unit": "percent"}, "25%",
     "Rental income vacancy factor — deduct 25% when using lease (no Schedule E).", None,
     "Fannie Mae B3-3.1-08", "https://selling-guide.fanniemae.com/sel/b3/3.1/08", "2026-06-01", "Accord compliance team"),
    ("fannie", "income", "se_income_years_required",
     {"type": "threshold", "value": 2, "unit": "years", "operator": "min"}, "2 years",
     "Self-employed income requires a 2-year history.", None,
     "Fannie Mae B3-3.4-01", "https://selling-guide.fanniemae.com/sel/b3/3.4/01", "2026-06-01", "Accord compliance team"),
    ("fannie", "income", "se_declining_use_lower_year",
     {"type": "boolean", "value": True}, "use lower year",
     "Self-employed declining income: use the lower (current) year, do not average.", None,
     "Fannie Mae B3-3.4-01", "https://selling-guide.fanniemae.com/sel/b3/3.4/01", "2026-06-01", "Accord compliance team"),

    # ── Property ──
    ("fannie", "property", "ineligible_property_types",
     {"type": "list", "value": ["vacant_land", "commercial", "cooperative"]},
     "vacant_land, commercial, cooperative",
     "Property types ineligible for conventional financing.", None,
     "Fannie Mae B2-1.3-01", "https://selling-guide.fanniemae.com/sel/b2/1.3/01", "2026-06-01", "Accord compliance team"),
    ("fannie", "property", "flood_zones_requiring_insurance",
     {"type": "list", "value": ["A", "AE", "AH", "AO", "V", "VE"]},
     "A, AE, AH, AO, V, VE",
     "Flood zones that require flood insurance before closing.", None,
     "Fannie Mae B7-3-02", "https://selling-guide.fanniemae.com/sel/b7/3/02", "2026-06-01", "Accord compliance team"),
    ("fannie", "property", "condo_warrantability_required",
     {"type": "boolean", "value": True}, "required",
     "Condo projects require a warrantability review before financing.", None,
     "Fannie Mae B4-2.1-01", "https://selling-guide.fanniemae.com/sel/b4/2.1/01", "2026-06-01", "Accord compliance team"),
    ("fannie", "property", "max_units_conventional",
     {"type": "threshold", "value": 4, "unit": "units", "operator": "max"}, "4 units",
     "Maximum number of units for a conventional loan.", None,
     "Fannie Mae B2-1.1-01", "https://selling-guide.fanniemae.com/sel/b2/1.1/01", "2026-06-01", "Accord compliance team"),
]


# Platform risk thresholds — outer bounds used by the fraud / collateral
# resolvers. Upserted into platform_guardrails (idempotent, ON CONFLICT
# DO NOTHING) so the existing per-product guardrails are not disturbed.
# (product_type, parameter, agency_floor, platform_ceiling, description)
GUARDRAILS = [
    ("platform", "income_mismatch_medium_pct",   None, 10,
     "Income mismatch >= 10% (URLA vs verified) -> medium fraud signal."),
    ("platform", "income_mismatch_high_pct",     None, 25,
     "Income mismatch >= 25% -> high fraud signal."),
    ("platform", "income_mismatch_critical_pct", None, 50,
     "Income mismatch >= 50% -> critical fraud signal (auto-block)."),
    ("platform", "appraisal_gap_major_pct",      None, 10,
     "Appraisal gap > 10% below purchase price -> major gap."),
    ("platform", "appraisal_gap_minor_pct",      None, 3,
     "Appraisal gap > 3% below purchase price -> minor gap."),
    ("platform", "undisclosed_debt_medium_mo",   None, 200,
     "Undisclosed monthly debt >= $200 -> medium signal."),
    ("platform", "undisclosed_debt_high_mo",      None, 500,
     "Undisclosed monthly debt >= $500 -> high signal."),
    ("platform", "undisclosed_debt_critical_mo", None, 1000,
     "Undisclosed monthly debt >= $1000 -> critical signal (auto-block)."),
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

        # Per-category counts (sanity check for the catalogue layer).
        cats = await conn.fetch(
            "SELECT category, count(*) AS c FROM agency_guidelines "
            "GROUP BY category ORDER BY category")
        for r in cats:
            print(f"  {r['category']:>10}: {r['c']}")

        # Platform risk thresholds — idempotent (ON CONFLICT DO NOTHING) so the
        # existing per-product guardrails are never disturbed.
        for product_type, parameter, floor, ceiling, desc in GUARDRAILS:
            await conn.execute(
                "INSERT INTO platform_guardrails "
                "(product_type, parameter, agency_floor, platform_ceiling, description) "
                "VALUES ($1,$2,$3,$4,$5) "
                "ON CONFLICT (product_type, parameter) DO NOTHING",
                product_type, parameter, floor, ceiling, desc,
            )
        g = await conn.fetchval(
            "SELECT count(*) FROM platform_guardrails WHERE product_type='platform'")
        print(f"platform_guardrails (product_type=platform): {g} rows")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())

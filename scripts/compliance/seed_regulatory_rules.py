"""Seed the federal + state regulatory layer (🔒 locked rules).

  python scripts/compliance/seed_regulatory_rules.py

Idempotent: clears regulatory_rules and re-inserts the canonical set (this table
is owned entirely by this seed). Reads DATABASE_URL from .env.
"""

import asyncio
import json
import os
from datetime import date

from dotenv import load_dotenv

load_dotenv()

# (authority, state_code, category, rule_name, rule_value, display_value, description, citation, effective_date)
FEDERAL = [
    ("qm", None, "dti", "QM Safe Harbor DTI Maximum",
     {"type": "threshold", "value": 43, "operator": "max"}, "43%",
     "General QM loans must have DTI ≤ 43% for safe harbor protection",
     "12 CFR 1026.43(e)(2)", "2023-10-01"),
    ("federal", None, "timeline", "Adverse Action Notice Deadline",
     {"type": "threshold", "value": 30, "unit": "days"}, "30 days",
     "Adverse action notice must be sent within 30 days of denial",
     "Regulation B §1002.9", "1974-10-28"),
    ("federal", None, "disclosure", "Adverse Action Specific Reasons",
     {"type": "requirement", "value": "specific_reasons_required"}, "Required",
     "Must provide specific reasons for adverse action, not generic",
     "Regulation B §1002.9(a)(2)", "1974-10-28"),
    ("federal", None, "timeline", "Loan Estimate Delivery",
     {"type": "threshold", "value": 3, "unit": "business_days"}, "3 business days",
     "LE must be provided within 3 business days of application",
     "Regulation Z §1026.19(e)", "2015-10-03"),
    ("federal", None, "timeline", "Closing Disclosure Delivery",
     {"type": "threshold", "value": 3, "unit": "business_days"}, "3 business days",
     "CD must be received 3 business days before closing",
     "Regulation Z §1026.19(f)", "2015-10-03"),
    ("ofac", None, "fraud", "OFAC SDN Screening",
     {"type": "requirement", "value": "mandatory", "cannot_disable": True}, "Required",
     "All borrowers must be screened against OFAC SDN list. Cannot be disabled.",
     "31 CFR Part 501", None),
    ("bsa", None, "fraud", "SAR Filing Requirement",
     {"type": "requirement", "value": "mandatory_on_suspicious_activity"}, "Required",
     "SAR must be filed for suspicious activity above $5,000",
     "31 CFR 1020.320", None),
    ("cfpb", None, "reporting", "HMDA Data Collection",
     {"type": "requirement", "value": "mandatory_for_covered_institutions"}, "Required",
     "Covered institutions must collect and report HMDA data",
     "Regulation C §1003", None),
]

STATE = [
    ("state", "TX", "ltv", "Texas Cash-Out Refinance LTV",
     {"type": "threshold", "value": 80, "operator": "max", "loan_purpose": "cash_out"}, "80% max",
     "Cash-out refinance limited to 80% LTV per Texas Constitution",
     "TX Const. Art. XVI §50(a)(6)", None),
    ("state", "TX", "timeline", "Texas Home Equity Cooling Period",
     {"type": "threshold", "value": 12, "unit": "days"}, "12 days",
     "12-day cooling period required for home equity loans",
     "TX Const. Art. XVI §50(a)(6)(M)", None),
    ("state", "NY", "rate", "New York Usury Cap",
     {"type": "threshold", "value": 16, "operator": "max", "unit": "percent"}, "16%",
     "Civil usury cap of 16% on residential mortgage loans",
     "NY Banking Law §14-a", None),
    ("state", "CA", "disclosure", "California MLDS Requirement",
     {"type": "requirement", "value": "mandatory"}, "Required",
     "Mortgage Loan Disclosure Statement required for CA properties",
     "CA Business & Professions Code §10240", None),
    ("state", "FL", "fee", "Florida Documentary Stamps",
     {"type": "threshold", "value": 0.70, "unit": "per_100"}, "$0.70/$100",
     "Documentary stamp tax required on all mortgages",
     "FL Statute §201.08", None),
    ("state", "IL", "disclosure", "Illinois High Risk Home Loan Disclosure",
     {"type": "requirement", "value": "mandatory_for_high_cost"}, "Required",
     "High-risk home loans require additional borrower disclosures and counseling",
     "815 ILCS 137 (High Risk Home Loan Act)", None),
    ("state", "PA", "timeline", "Pennsylvania Act 91 Pre-Foreclosure Notice",
     {"type": "threshold", "value": 30, "unit": "days"}, "30 days",
     "Act 91 notice required 30 days before foreclosure on residential mortgages",
     "PA Act 6 of 1974 / Act 91", None),
    ("state", "OH", "disclosure", "Ohio Homebuyers Protection High-Cost Disclosure",
     {"type": "requirement", "value": "mandatory_for_high_cost"}, "Required",
     "High-cost home loans require enhanced disclosures and limits on terms",
     "Ohio S.B. 185 (Homebuyers Protection Act)", None),
    ("state", "GA", "fee", "Georgia Fair Lending High-Cost Threshold",
     {"type": "threshold", "value": 5, "operator": "max", "unit": "percent_points_fees"}, "5% points/fees",
     "Home loans exceeding 5% total points and fees are 'high-cost' with added limits",
     "Georgia Fair Lending Act (O.C.G.A. §7-6A)", None),
    ("state", "NC", "rate", "North Carolina High-Cost Rate Spread",
     {"type": "threshold", "value": 8, "operator": "max", "unit": "percent_over_treasury"}, "8% over Treasury",
     "Rate spread above 8% over comparable Treasury triggers high-cost loan limits",
     "N.C.G.S. §24-1.1E (Predatory Lending)", None),
    ("state", "VA", "disclosure", "Virginia Mortgage Disclosure Requirement",
     {"type": "requirement", "value": "mandatory"}, "Required",
     "Licensed lenders must provide Virginia mortgage disclosure to borrowers",
     "Va. Code §6.2-1600 (Mortgage Lender & Broker Act)", None),
]


async def main() -> None:
    import asyncpg

    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL not set")
    conn = await asyncpg.connect(url)
    try:
        async with conn.transaction():
            await conn.execute("DELETE FROM regulatory_rules")
            for authority, state, cat, name, val, disp, desc, cite, eff in FEDERAL + STATE:
                await conn.execute(
                    "INSERT INTO regulatory_rules "
                    "(authority, state_code, category, rule_name, rule_value, display_value, description, citation, effective_date) "
                    "VALUES ($1,$2,$3,$4,$5::jsonb,$6,$7,$8,$9)",
                    authority, state, cat, name, json.dumps(val), disp, desc, cite,
                    date.fromisoformat(eff) if eff else None,
                )
        n = await conn.fetchval("SELECT count(*) FROM regulatory_rules")
        print(f"Seeded regulatory_rules: {n} rows ({len(FEDERAL)} federal, {len(STATE)} state)")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())

"""
INC-E — seed the retirement / SS / asset-depletion / investment income rules so
the RetirementIncomeResolver reads them from the catalogue (RULE 8: catalogue
before code). All Fannie B3-3.1-09, agency layer, category 'income'. Idempotent
existence-check; JSONB threshold/factor shape (matches the prior seeds).

  ss_non_taxable_gross_up_factor            = 1.25  (non-taxable income gross-up)
  ss_continuance_months_required            = 36    (3-yr continuance)
  retirement_continuance_months_required    = 36
  asset_depletion_divisor_months            = 360
  asset_depletion_retirement_haircut_pct    = 70
  asset_depletion_cash_haircut_pct          = 100
  asset_depletion_equity_haircut_pct        = 70
  dividend_interest_history_months_required = 24

  python scripts/compliance/seed_inc_e_retirement_rules.py
"""
import asyncio
import json
import os
from dotenv import load_dotenv
load_dotenv()

_CITE = "Fannie Mae Selling Guide B3-3.1-09"

# (guideline_name, value, display, description)
ROWS = [
    ("ss_non_taxable_gross_up_factor", 1.25, "1.25x",
     "Non-taxable income (e.g. Social Security) may be grossed up by 25% when "
     "qualifying, since the borrower's effective spendable income is higher."),
    ("ss_continuance_months_required", 36, "36 months",
     "Social Security income must be expected to continue at least 3 years to "
     "be used for qualifying."),
    ("retirement_continuance_months_required", 36, "36 months",
     "Pension / retirement income must be expected to continue at least 3 years "
     "to be used for qualifying."),
    ("asset_depletion_divisor_months", 360, "360 months",
     "Asset-depletion / employment-related-assets income = eligible assets "
     "divided by the amortization term (360 months)."),
    ("asset_depletion_retirement_haircut_pct", 70, "70%",
     "Only 70% of retirement assets count as eligible for asset depletion "
     "(discount for taxes/withdrawal penalties)."),
    ("asset_depletion_cash_haircut_pct", 100, "100%",
     "100% of cash / liquid savings counts as eligible for asset depletion."),
    ("asset_depletion_equity_haircut_pct", 70, "70%",
     "Only 70% of stock/bond/equity assets count as eligible for asset "
     "depletion (market-volatility discount)."),
    ("dividend_interest_history_months_required", 24, "24 months",
     "Dividend / interest income requires a 2-year (24-month) history and is "
     "qualified as the 2-year average."),
]


def _gv(value) -> str:
    if isinstance(value, bool):
        return json.dumps({"type": "boolean", "value": value})
    if isinstance(value, (int, float)):
        return json.dumps({"type": "threshold", "value": value})
    return json.dumps({"type": "treatment", "value": value})


def _u():
    return os.environ["DATABASE_URL"].replace("+asyncpg", "").replace(
        "postgresql+psycopg2", "postgresql")


async def main():
    import asyncpg
    conn = await asyncpg.connect(_u())
    try:
        print("-- seed agency_guidelines (INC-E retirement/SS/depletion/investment) --")
        for name, value, disp, desc in ROWS:
            exists = await conn.fetchval(
                """SELECT 1 FROM agency_guidelines
                   WHERE agency='fannie' AND guideline_name=$1
                   AND valid_to IS NULL AND is_active = true LIMIT 1""",
                name,
            )
            if exists:
                print(f"  fannie/{name}: already present, skipping")
                continue
            await conn.execute(
                """INSERT INTO agency_guidelines
                   (agency, category, guideline_name, guideline_value,
                    display_value, description, citation, source_url,
                    effective_date, last_verified, verified_by,
                    valid_from, source_revision)
                   VALUES ('fannie','income',$1,$2::jsonb,$3,$4,$5,
                           'https://selling-guide.fanniemae.com',
                           CURRENT_DATE, CURRENT_DATE, 'Accord compliance team',
                           CURRENT_DATE, 'INC-E')""",
                name, _gv(value), disp, desc, _CITE,
            )
            print(f"  fannie/{name} = {value} (inserted)  [{_CITE}]")

        print("\n-- verify (INC-E rows) --")
        for r in await conn.fetch(
            """SELECT guideline_name, guideline_value FROM agency_guidelines
               WHERE source_revision='INC-E' AND valid_to IS NULL
               ORDER BY guideline_name"""):
            print(f"  {r['guideline_name']}: {r['guideline_value']}")
        total = await conn.fetchval(
            "SELECT COUNT(*) FROM agency_guidelines WHERE valid_to IS NULL AND is_active=true")
        print(f"\n  total active agency_guidelines: {total}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())

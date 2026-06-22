"""
Verify the catalogue is RA-4-ready: every rule the resolvers will read through
rule_loader must resolve from the catalogue (governed_by agency/regulatory/
overlay) — NOT fall through to a SAFE_DEFAULT. A safe_default here means the
rule isn't catalogued under the canonical name and RA-4 would silently use a
hardcoded fallback.

  python scripts/verify_catalogue_ready.py

Exit 0 if ready, 1 if any required rule is missing/safe-defaulted.
"""
import asyncio
import os
import sys
from dotenv import load_dotenv
load_dotenv()
sys.path.insert(0, ".")

TENANT = "meridian"

# (guideline_name, [agencies]) — the canonical rule contract resolvers consume.
REQUIRED = [
    # Asset (Fannie B3-4.3-04)
    ("qualifying_factor_checking", ["fannie"]),
    ("qualifying_factor_savings", ["fannie"]),
    ("qualifying_factor_cd", ["fannie"]),
    ("qualifying_factor_retirement", ["fannie"]),
    ("qualifying_factor_stocks_bonds", ["fannie"]),
    ("qualifying_factor_crypto", ["fannie"]),
    ("minimum_reserves_months", ["fannie"]),
    ("large_deposit_threshold_pct", ["fannie"]),
    ("seasoning_days_required", ["fannie"]),
    # Credit waiting periods (per agency — Fannie B3-5.3-07 / HUD / VA)
    ("bankruptcy_ch7_waiting_years", ["fannie", "fha", "va"]),
    ("bankruptcy_ch13_waiting_years", ["fannie", "fha", "va"]),
    ("foreclosure_waiting_years", ["fannie", "fha", "va"]),
    ("short_sale_waiting_years", ["fannie", "fha", "va"]),
    ("deed_in_lieu_waiting_years", ["fannie", "fha", "va"]),
    # Income / liabilities
    ("student_loan_deferred_rate_pct", ["fannie"]),
    ("medical_collection_excluded", ["fannie"]),
    ("rental_vacancy_factor_pct", ["fannie"]),
    ("se_income_years_required", ["fannie"]),
    ("se_declining_use_lower_year", ["fannie"]),
    ("se_depreciation_addback", ["fannie"]),
    ("income_documentation_confidence_min", ["fannie"]),
    ("income_documentation_confidence_floor", ["fannie"]),
    ("income_mismatch_medium_pct", ["fannie"]),
    ("income_mismatch_high_pct", ["fannie"]),
    ("income_mismatch_critical_pct", ["fannie"]),
    ("undisclosed_debt_medium_mo", ["fannie"]),
    ("undisclosed_debt_high_mo", ["fannie"]),
    ("undisclosed_debt_critical_mo", ["fannie"]),
    # Property / collateral
    ("ineligible_property_types", ["fannie"]),
    ("flood_zones_requiring_insurance", ["fannie"]),
    ("condo_warrantability_required", ["fannie"]),
    ("max_units_conventional", ["fannie"]),
    ("appraisal_gap_major_pct", ["fannie"]),
    ("appraisal_gap_minor_pct", ["fannie"]),
    # Title liens (Fannie B8-1-01/02)
    ("lien_solar_panel_treatment", ["fannie"]),
    ("lien_irs_tax_treatment", ["fannie"]),
    ("lien_hoa_treatment", ["fannie"]),
    ("lien_mechanics_treatment", ["fannie"]),
    # ── RA-SEED-C (pre-RA-4F mini seed pass) — gated from RA-4F/G onward ──
    # Compliance boundary suite (HUD 4000.1)
    ("FHA Absolute Minimum Score (10pct down)", ["fha"]),
    # Credit / income / asset (Fannie B3-5.3-07 / B3-6-05 / B3-3.4-01)
    ("Judgment Waiting Period", ["fannie"]),
    ("Installment Debt Months Remaining Exclusion", ["fannie"]),
    ("Self-Employed Business Ownership Majority", ["fannie"]),
    ("Self-Employed Full Business Asset Credit", ["fannie"]),
    ("Self-Employed Partial Business Asset Credit", ["fannie"]),
    # Title liens (Fannie B8-1-02)
    ("lien_tax_property_treatment", ["fannie"]),
    ("lien_state_tax_treatment", ["fannie"]),
    ("lien_judgment_treatment", ["fannie"]),
    ("lien_child_support_treatment", ["fannie"]),
    ("lien_lis_pendens_treatment", ["fannie"]),
]


def _u():
    return os.environ["DATABASE_URL"].replace("+asyncpg", "").replace(
        "postgresql+psycopg2", "postgresql")


async def main() -> int:
    import asyncpg
    from core.catalogue.rule_loader import get_rule

    conn = await asyncpg.connect(_u(), timeout=20)
    ok, bad = 0, []
    try:
        for name, agencies in REQUIRED:
            for agency in agencies:
                r = await get_rule(conn, name, TENANT, agency=agency)
                applied = r.get("applied")
                gov = r.get("governed_by")
                ready = (
                    applied is not None
                    and not r.get("using_default")
                    and gov in ("agency", "regulatory", "overlay")
                )
                if ready:
                    ok += 1
                else:
                    bad.append((agency, name, applied, gov))
    finally:
        await conn.close()

    total = ok + len(bad)
    print("=" * 60)
    print("CATALOGUE READINESS — RA-4")
    print("=" * 60)
    print(f"Resolved from catalogue: {ok}/{total}")
    if bad:
        print(f"\nNOT READY ({len(bad)}):")
        for agency, name, applied, gov in bad:
            print(f"  x {agency}/{name}: applied={applied!r} governed_by={gov}")
        print("\nRESULT: NOT READY — seed/rename the rules above before RA-4.")
        return 1
    print("\nRESULT: READY — every required rule resolves from the catalogue.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

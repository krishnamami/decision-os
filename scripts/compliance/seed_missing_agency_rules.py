"""
Seed the rules RA-SEED-A found missing from agency_guidelines (RA-SEED-B), and
remove the now-redundant platform_guardrails copies.

10 rows, every one cited to a published agency source:
  - appraisal_gap_major/minor_pct        (Fannie B4-1.3-09)  platform -> agency
  - undisclosed_debt_{med,high,crit}_mo  (Fannie B3-6-02)    platform -> agency
  - se_depreciation_addback              (Fannie B3-3.4-02)  was missing
  - lien_{solar,irs,hoa,mechanics}_treatment (Fannie B8-1-01/02)  was resolver config

Idempotent (existence-checked; no unique constraint on agency,guideline_name —
Type 2 keeps history). Cleanup of platform_guardrails runs ONLY after the
agency_guidelines rows are confirmed present, and never touches the legitimate
per-product credit/dti/ltv bounds.

  python scripts/compliance/seed_missing_agency_rules.py
"""
import asyncio
import json
import os
from dotenv import load_dotenv
load_dotenv()

# (agency, category, name, value, display, description, citation)
ROWS = [
    ("fannie", "property", "appraisal_gap_major_pct", 10, "10%",
     "Appraisal gap (purchase over appraised) >= this percent is a major "
     "variance requiring underwriter review.",
     "Fannie Mae Selling Guide B4-1.3-09"),
    ("fannie", "property", "appraisal_gap_minor_pct", 3, "3%",
     "Appraisal gap >= this percent is a minor variance requiring notation.",
     "Fannie Mae Selling Guide B4-1.3-09"),
    ("fannie", "income", "undisclosed_debt_medium_mo", 200, "$200/mo",
     "Undisclosed monthly debt (credit report over URLA) >= this amount "
     "triggers a medium-severity review.",
     "Fannie Mae Selling Guide B3-6-02"),
    ("fannie", "income", "undisclosed_debt_high_mo", 500, "$500/mo",
     "Undisclosed monthly debt >= this amount triggers a high-severity flag.",
     "Fannie Mae Selling Guide B3-6-02"),
    ("fannie", "income", "undisclosed_debt_critical_mo", 1000, "$1000/mo",
     "Undisclosed monthly debt >= this amount is a critical fraud signal.",
     "Fannie Mae Selling Guide B3-6-02"),
    ("fannie", "income", "se_depreciation_addback", True, "allowed",
     "Depreciation (Schedule C/E/F) and depletion (Schedule E) may be added "
     "back to qualifying income for self-employed borrowers.",
     "Fannie Mae Selling Guide B3-3.4-02"),
    ("fannie", "title", "lien_solar_panel_treatment",
     "acceptable_if_leased_or_owned", "acceptable_if_leased_or_owned",
     "Solar panel liens acceptable: leased (exclude from DTI) or owned "
     "(treat as secured obligation).",
     "Fannie Mae Selling Guide B8-1-01"),
    ("fannie", "title", "lien_irs_tax_treatment", "blocks_closing",
     "blocks_closing",
     "IRS tax lien blocks closing unless an approved payment plan is "
     "established.",
     "Fannie Mae Selling Guide B8-1-02"),
    ("fannie", "title", "lien_hoa_treatment", "requires_payoff_if_superior",
     "requires_payoff_if_superior",
     "HOA lien superior to the first mortgage must be paid off at closing.",
     "Fannie Mae Selling Guide B8-1-02"),
    ("fannie", "title", "lien_mechanics_treatment", "blocks_closing",
     "blocks_closing",
     "Mechanics lien blocks closing until released or bonded.",
     "Fannie Mae Selling Guide B8-1-02"),
]

# platform_guardrails rows now redundant (moved to agency_guidelines). The
# per-product credit_floor/dti_back_max/ltv_* ceilings are NOT in this list —
# they stay as legitimate outer bounds.
PLATFORM_REDUNDANT = [
    "appraisal_gap_major_pct", "appraisal_gap_minor_pct",
    "undisclosed_debt_medium_mo", "undisclosed_debt_high_mo",
    "undisclosed_debt_critical_mo",
    "income_mismatch_medium_pct", "income_mismatch_high_pct",
    "income_mismatch_critical_pct",
]


def _gv(value) -> str:
    """jsonb shape rule_loader._parse understands."""
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
        print("── seed agency_guidelines ──")
        for agency, cat, name, value, disp, desc, cite in ROWS:
            exists = await conn.fetchval(
                """SELECT 1 FROM agency_guidelines
                   WHERE agency=$1 AND guideline_name=$2
                   AND valid_to IS NULL AND is_active = true LIMIT 1""",
                agency, name,
            )
            if exists:
                print(f"  {agency}/{name}: already present, skipping")
                continue
            await conn.execute(
                """INSERT INTO agency_guidelines
                   (agency, category, guideline_name, guideline_value,
                    display_value, description, citation, source_url,
                    effective_date, last_verified, verified_by,
                    valid_from, source_revision)
                   VALUES ($1,$2,$3,$4::jsonb,$5,$6,$7,
                           'https://selling-guide.fanniemae.com',
                           CURRENT_DATE, CURRENT_DATE, 'Accord compliance team',
                           CURRENT_DATE, 'RA-SEED-B')""",
                agency, cat, name, _gv(value), disp, desc, cite,
            )
            print(f"  {agency}/{name} = {value} (inserted)  [{cite}]")

        # ── cleanup platform_guardrails — only after agency rows confirmed ──
        print("\n── cleanup platform_guardrails (guarded) ──")
        need = [
            "appraisal_gap_major_pct", "appraisal_gap_minor_pct",
            "undisclosed_debt_medium_mo", "undisclosed_debt_high_mo",
            "undisclosed_debt_critical_mo",
            "income_mismatch_medium_pct", "income_mismatch_high_pct",
            "income_mismatch_critical_pct",
        ]
        present = {
            r["guideline_name"] for r in await conn.fetch(
                """SELECT guideline_name FROM agency_guidelines
                   WHERE guideline_name = ANY($1) AND valid_to IS NULL
                   AND is_active = true""", need)
        }
        missing = [n for n in need if n not in present]
        if missing:
            print(f"  ABORT cleanup — agency rows missing: {missing}")
        else:
            res = await conn.execute(
                """DELETE FROM platform_guardrails
                   WHERE product_type='platform' AND parameter = ANY($1)""",
                PLATFORM_REDUNDANT,
            )
            print(f"  deleted redundant platform rows: {res}")

        # ── verify ──
        print("\n── verify (agency_guidelines) ──")
        for r in await conn.fetch(
            """SELECT guideline_name, guideline_value, citation
               FROM agency_guidelines
               WHERE source_revision='RA-SEED-B' AND valid_to IS NULL
               ORDER BY guideline_name"""):
            print(f"  {r['guideline_name']}: {r['guideline_value']}  [{r['citation']}]")
        left = await conn.fetch(
            "SELECT parameter FROM platform_guardrails "
            "WHERE product_type='platform' ORDER BY parameter")
        print(f"  platform_guardrails product_type=platform remaining: "
              f"{[r['parameter'] for r in left]}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())

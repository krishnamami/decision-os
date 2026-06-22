"""
Seed the 5 uncatalogued items flagged during RA-4A..RA-4E that must exist in
agency_guidelines before RA-4F (fraud) / RA-4G (income) can read them through
rule_loader instead of hardcoding. Mini seed pass (RA-SEED-C), 11 rows total,
every one cited to a published agency source:

  ITEM 1  FHA Absolute Minimum Score (10pct down)   500  (HUD 4000.1 IV.A.1.a)
          closes the last safe_default in the rule_validator boundary suite
  ITEM 2  Judgment Waiting Period                     7y  (Fannie B3-5.3-07)
  ITEM 3  Installment Debt Months Remaining Exclusion 10  (Fannie B3-6-05)
  ITEM 4  Self-Employed Business Ownership tiers   25/100/50  (Fannie B3-3.4-01)
  ITEM 5  5 lien treatments (tax/state-tax/judgment/child-support/lis-pendens)
          all blocks_closing                            (Fannie B8-1-02)

Naming follows the EXISTING convention per family (verified against live RDS):
the FHA/credit/income/asset families are human-named; the lien family is
snake_case (lien_<type>_treatment) to match the 4 RA-SEED-B lien rows and the
LIEN_TYPE_TO_RULE_KEY / SAFE_DEFAULTS keys. Child support is seeded blocks_closing
(NOT requires_payoff) so wiring it preserves its structural auto_block=True — no
decision-logic change.

Idempotent (existence-checked; no unique constraint on agency,guideline_name —
Type 2 keeps history). Does NOT touch any resolver logic, persona, or the
evidence graph — catalogue rows only.

  python scripts/compliance/seed_pre_ra4f_rules.py
"""
import asyncio
import json
import os
from dotenv import load_dotenv
load_dotenv()

# (agency, category, guideline_name, value, display, description, citation)
ROWS = [
    # ── ITEM 1 — FHA absolute minimum credit score ──────────────────────────
    ("fha", "credit", "FHA Absolute Minimum Score (10pct down)", 500, "500",
     "Absolute FHA minimum credit score requiring 10% down payment. Below 580 "
     "requires 10% down; below 500 is ineligible regardless of down payment.",
     "HUD Handbook 4000.1 IV.A.1.a"),
    # ── ITEM 2 — judgment waiting period (credit event) ─────────────────────
    ("fannie", "credit", "Judgment Waiting Period", 7, "7 years",
     "Judgment lien must be paid off or on an approved payment plan; 7-year "
     "waiting period before eligible (3yr with extenuating circumstances, 2yr "
     "for VA).",
     "Fannie Mae Selling Guide B3-5.3-07"),
    # ── ITEM 3 — installment debt months-remaining exclusion ────────────────
    ("fannie", "income", "Installment Debt Months Remaining Exclusion", 10,
     "10 months",
     "Installment debts with 10 or fewer months remaining may be excluded from "
     "DTI at underwriter discretion.",
     "Fannie Mae Selling Guide B3-6-05"),
    # ── ITEM 4 — self-employed business ownership tiers ─────────────────────
    ("fannie", "income", "Self-Employed Business Ownership Majority", 25, "25%",
     "A borrower with 25% or more ownership interest in a business is treated "
     "as self-employed for income qualification purposes.",
     "Fannie Mae Selling Guide B3-3.4-01"),
    ("fannie", "asset", "Self-Employed Full Business Asset Credit", 100, "100%",
     "A sole proprietor (100% ownership) may use 100% of business assets toward "
     "reserves with 2 months of business bank statements.",
     "Fannie Mae Selling Guide B3-3.4-01"),
    ("fannie", "asset", "Self-Employed Partial Business Asset Credit", 50, "50%",
     "A partial business owner may use their ownership percentage of business "
     "assets toward reserves (e.g. a 50% owner gets 50% credit).",
     "Fannie Mae Selling Guide B3-3.4-01"),
    # ── ITEM 5 — lien treatments (snake_case, matches existing lien family) ──
    ("fannie", "title", "lien_tax_property_treatment", "blocks_closing",
     "blocks_closing",
     "Property tax lien blocks closing unless on an approved payment plan.",
     "Fannie Mae Selling Guide B8-1-02"),
    ("fannie", "title", "lien_state_tax_treatment", "blocks_closing",
     "blocks_closing",
     "State income tax lien blocks closing unless on an approved payment plan.",
     "Fannie Mae Selling Guide B8-1-02"),
    ("fannie", "title", "lien_judgment_treatment", "blocks_closing",
     "blocks_closing",
     "Judgment lien blocks closing unless paid off or subordinated.",
     "Fannie Mae Selling Guide B8-1-02"),
    ("fannie", "title", "lien_child_support_treatment", "blocks_closing",
     "blocks_closing",
     "Child support lien blocks closing until paid at or before closing "
     "(consistent with auto_block treatment).",
     "Fannie Mae Selling Guide B8-1-02"),
    ("fannie", "title", "lien_lis_pendens_treatment", "blocks_closing",
     "blocks_closing",
     "Lis pendens (notice of pending lawsuit) blocks closing until the suit is "
     "resolved.",
     "Fannie Mae Selling Guide B8-1-02"),
]


def _gv(value) -> str:
    """jsonb shape rule_loader._parse understands (matches seed_missing_agency_rules)."""
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
        print("── seed agency_guidelines (RA-SEED-C) ──")
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
                           CURRENT_DATE, 'RA-SEED-C')""",
                agency, cat, name, _gv(value), disp, desc, cite,
            )
            print(f"  {agency}/{name} = {value} (inserted)  [{cite}]")

        # ── verify ──
        print("\n── verify (RA-SEED-C rows) ──")
        for r in await conn.fetch(
            """SELECT guideline_name, guideline_value, agency, citation
               FROM agency_guidelines
               WHERE source_revision='RA-SEED-C' AND valid_to IS NULL
               ORDER BY guideline_name"""):
            print(f"  [{r['agency']:7}] {r['guideline_name']}: "
                  f"{r['guideline_value']}  [{r['citation']}]")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())

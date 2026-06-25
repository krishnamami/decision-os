"""EV-G (RULE 8) — seed document staleness / recency rules into agency_guidelines.

No document-staleness rules existed in the catalogue (only seasoning_days_required,
a large-deposit rule). These let core/evidence/staleness_checker.StalenessChecker
read its thresholds from the catalogue instead of hardcoding them.

  appraisal_validity_days_conventional = 120   (Fannie B3-4.3-05)
  appraisal_validity_days_fha          = 180   (HUD Handbook 4000.1 II.A.1.a)
  paystub_max_age_days                 = 30    (Fannie B3-2-10)
  bank_statement_max_age_days          = 60    (Fannie B3-2-10)
  credit_report_validity_days          = 120   (Fannie B3-5.3-01)
  w2_tax_year_lookback_years           = 2     (Fannie B3-3.1-01)
  tax_return_lookback_years            = 2     (Fannie B3-3.1-02)
  rate_lock_must_exceed_closing        = true  (lender requirement)
  hoi_must_be_current                  = true  (Fannie B7-2-03)

Idempotent; JSONB shape; agency layer, category 'document'. Run:
  PYTHONIOENCODING=utf-8 PYTHONUTF8=1 python scripts/compliance/seed_ev_g_staleness_rules.py
"""
import asyncio
import json
import os

from dotenv import load_dotenv

load_dotenv()

ROWS = [
    ("appraisal_validity_days_conventional", 120, "120 days",
     "Appraisal must be dated within 120 days of the note date (conventional).",
     "Fannie Mae Selling Guide B3-4.3-05"),
    ("appraisal_validity_days_fha", 180, "180 days",
     "Appraisal validity is 180 days for FHA 1-4 unit.",
     "HUD Handbook 4000.1 II.A.1.a"),
    ("paystub_max_age_days", 30, "30 days",
     "Most recent paystub must be dated within 30 days of the note date.",
     "Fannie Mae Selling Guide B3-2-10"),
    ("bank_statement_max_age_days", 60, "60 days",
     "Bank statement must be dated within 60 days of the note date.",
     "Fannie Mae Selling Guide B3-2-10"),
    ("credit_report_validity_days", 120, "120 days",
     "Credit report must be dated within 120 days of the note date.",
     "Fannie Mae Selling Guide B3-5.3-01"),
    ("w2_tax_year_lookback_years", 2, "2 years",
     "W2 must be from the prior or current tax year (2-year lookback).",
     "Fannie Mae Selling Guide B3-3.1-01"),
    ("tax_return_lookback_years", 2, "2 years",
     "Tax returns must cover the prior two tax years.",
     "Fannie Mae Selling Guide B3-3.1-02"),
    ("rate_lock_must_exceed_closing", True, "true",
     "The rate-lock expiration date must be on or after the closing/note date.",
     "Lender requirement"),
    ("hoi_must_be_current", True, "true",
     "The homeowner's insurance binder must be in force (not expired) at closing.",
     "Fannie Mae Selling Guide B7-2-03"),
]


def _gv(value) -> str:
    if isinstance(value, bool):
        return json.dumps({"type": "boolean", "value": value})
    if isinstance(value, (int, float)):
        return json.dumps({"type": "threshold", "value": value, "unit": "days"})
    return json.dumps({"type": "treatment", "value": value})


def _u():
    return os.environ["DATABASE_URL"].replace("+asyncpg", "").replace(
        "postgresql+psycopg2", "postgresql")


async def main():
    import asyncpg
    conn = await asyncpg.connect(_u())
    try:
        print("-- seed agency_guidelines (EV-G document staleness rules) --")
        for name, value, disp, desc, cite in ROWS:
            exists = await conn.fetchval(
                """SELECT 1 FROM agency_guidelines
                   WHERE agency='fannie' AND guideline_name=$1
                   AND valid_to IS NULL AND is_active = true LIMIT 1""", name)
            if exists:
                print(f"  fannie/{name}: already present, skipping")
                continue
            await conn.execute(
                """INSERT INTO agency_guidelines
                   (agency, category, guideline_name, guideline_value,
                    display_value, description, citation, source_url,
                    effective_date, last_verified, verified_by,
                    valid_from, source_revision)
                   VALUES ('fannie','document',$1,$2::jsonb,$3,$4,$5,
                           'https://selling-guide.fanniemae.com',
                           CURRENT_DATE, CURRENT_DATE, 'Accord compliance team',
                           CURRENT_DATE, 'EV-G')""",
                name, _gv(value), disp, desc, cite)
            print(f"  fannie/{name} = {value} (inserted)  [{cite}]")

        print("\n-- verify --")
        for r in await conn.fetch(
            """SELECT guideline_name, guideline_value, citation FROM agency_guidelines
               WHERE source_revision='EV-G' AND valid_to IS NULL ORDER BY guideline_name"""):
            print(f"  {r['guideline_name']}: {r['guideline_value']}  ({r['citation']})")
        total = await conn.fetchval(
            "SELECT COUNT(*) FROM agency_guidelines WHERE valid_to IS NULL AND is_active=true")
        print(f"\n  total active agency_guidelines: {total}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())

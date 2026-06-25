"""
EX-C Part 0/1 — seed the exception approver hierarchy + de-hardcode the EX-B
score→approval-level thresholds (RULE 8; closes the RULE 1 gap EX-B left where
9/5/2 were hardcoded in CompensatingFactorsEngine.detect_all). Fannie B3-2-02,
agency layer, category 'exception'. Idempotent; JSONB shape.

  exception_score_senior_min   = 9   (>= 9 -> senior_uw_approval)
  exception_score_manager_min  = 5   (>= 5 -> uw_manager_approval)
  exception_score_uw_min       = 2   (>= 2 -> uw_approval; else insufficient)
  approver_uw_role             = uw
  approver_manager_role        = uw_manager
  approver_senior_role         = senior_credit_officer

  python scripts/compliance/seed_ex_c_approver_hierarchy.py
"""
import asyncio
import json
import os
from dotenv import load_dotenv
load_dotenv()

_CITE = "Fannie Mae Selling Guide B3-2-02"
ROWS = [
    ("exception_score_senior_min", 9, "9",
     "Compensating-factor exception_score >= 9 requires senior credit approval."),
    ("exception_score_manager_min", 5, "5",
     "exception_score >= 5 requires UW manager approval."),
    ("exception_score_uw_min", 2, "2",
     "exception_score >= 2 may be approved by a standard UW; below 2 is insufficient."),
    ("approver_uw_role", "uw", "uw",
     "Role that may approve uw_approval-level exceptions."),
    ("approver_manager_role", "uw_manager", "uw_manager",
     "Role that may approve uw_manager_approval-level exceptions."),
    ("approver_senior_role", "senior_credit_officer", "senior_credit_officer",
     "Role that may approve senior_uw_approval-level exceptions."),
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
        print("-- seed agency_guidelines (EX-C approver hierarchy + score thresholds) --")
        for name, value, disp, desc in ROWS:
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
                   VALUES ('fannie','exception',$1,$2::jsonb,$3,$4,$5,
                           'https://selling-guide.fanniemae.com',
                           CURRENT_DATE, CURRENT_DATE, 'Accord compliance team',
                           CURRENT_DATE, 'EX-C')""",
                name, _gv(value), disp, desc, _CITE)
            print(f"  fannie/{name} = {value} (inserted)  [{_CITE}]")

        print("\n-- verify --")
        for r in await conn.fetch(
            """SELECT guideline_name, guideline_value FROM agency_guidelines
               WHERE source_revision='EX-C' AND valid_to IS NULL ORDER BY guideline_name"""):
            print(f"  {r['guideline_name']}: {r['guideline_value']}")
        total = await conn.fetchval(
            "SELECT COUNT(*) FROM agency_guidelines WHERE valid_to IS NULL AND is_active=true")
        print(f"\n  total active agency_guidelines: {total}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())

"""Seed Summit's Comparison Mode demo (Part 7).

  python scripts/compliance/seed_comparison_demo.py

An active 90-day period (started 22 days ago) + 30 comparison decisions:
26 agree, 1 Accord-caught fraud, 3 Accord-stricter DTI disagreements resolved
for manual. ~86.7% agreement, improving weekly trend. ONLY touches 'summit'.
Idempotent (delete + reinsert).
"""

import asyncio
import os
from datetime import datetime, timedelta

from dotenv import load_dotenv

load_dotenv()

TID = "summit"

# Non-agreement cases (the interesting ones). (accord, manual, agreement, week, details, resolution)
SPECIAL = [
    ("escalate", "approved", "accord_stricter", 1,
     "Accord flagged an employer phone mismatch; manual review approved.",
     "Accord was right — the employer phone was a Google Voice number and the VOE was fraudulent. Loan subsequently suspended."),
    ("block", "approved", "accord_stricter", 1,
     "Accord blocked for DTI 43.5% over the 43% limit; underwriter approved with compensating factors.",
     "Manual was appropriate — 12 months reserves and a 760 score justify the exception per Selling Guide B3-6-02."),
    ("block", "approved", "accord_stricter", 1,
     "Accord blocked for DTI 44.2%; underwriter approved citing strong reserves.",
     "Manual was appropriate — compensating factors (reserves + credit) justify the exception."),
    ("block", "approved", "accord_stricter", 2,
     "Accord blocked for DTI 43.8%; underwriter approved with a strong file.",
     "Manual was appropriate — compensating factors justify the exception. Conditional rules updated to handle DTI 43-50% with credit >=720 and reserves >=6mo."),
]

# 26 agreements distributed by week to produce an improving trend.
AGREE_WEEKS = [1] * 5 + [2] * 7 + [3] * 8 + [4] * 6


async def main() -> None:
    import asyncpg

    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL not set")
    conn = await asyncpg.connect(url)
    try:
        admin = await conn.fetchval("SELECT user_id FROM users WHERE tenant_id=$1 AND role='admin' LIMIT 1", TID)
        apps = await conn.fetch(
            """SELECT es.application_id, ap.full_name FROM entity_states es
               LEFT JOIN applications a ON a.application_id = es.application_id
               LEFT JOIN applicants ap ON ap.applicant_id = a.applicant_id
               WHERE es.tenant_id=$1 ORDER BY es.application_id LIMIT 30""", TID)
        if len(apps) < 30:
            raise SystemExit(f"Need 30 summit loans, found {len(apps)}")

        started = datetime.utcnow() - timedelta(days=22)
        ends = started + timedelta(days=90)

        async with conn.transaction():
            await conn.execute("DELETE FROM comparison_decisions WHERE tenant_id=$1", TID)
            await conn.execute("DELETE FROM comparison_periods WHERE tenant_id=$1", TID)
            period_id = await conn.fetchval(
                "INSERT INTO comparison_periods (tenant_id, started_at, started_by, ends_at, status, total_loans) "
                "VALUES ($1,$2,$3,$4,'active',30) RETURNING period_id",
                TID, started, admin, ends)

            async def insert(app, name, accord, manual, agreement, week, details, resolution, conf):
                created = started + timedelta(days=(week - 1) * 7 + (hash(app) % 6))
                await conn.execute(
                    "INSERT INTO comparison_decisions (application_id, tenant_id, accord_outcome, accord_confidence, "
                    " accord_reasoning, accord_decided_at, manual_outcome, manual_decided_by, manual_reasoning, "
                    " manual_decided_at, agreement, agreement_details, resolution, loan_performance, created_at) "
                    "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$6)",
                    app, TID, accord, conf, f"Accord recommended {accord}.", created, manual, admin,
                    "Strong compensating factors." if manual == "approved" and accord in ("block", "escalate") else f"Underwriter {manual}.",
                    created, agreement, details, resolution, "performing")

            # special (non-agreement) cases — first 4 apps
            for i, (accord, manual, agreement, week, details, resolution) in enumerate(SPECIAL):
                await insert(apps[i]["application_id"], apps[i]["full_name"], accord, manual, agreement, week, details, resolution, 0.91 + i * 0.01)

            # 26 agreements — alternate good (allow/approved) and bad (block/denied)
            for j, week in enumerate(AGREE_WEEKS):
                app = apps[4 + j]
                good = j % 3 != 0  # ~2/3 approvals
                accord, manual = ("allow", "approved") if good else ("block", "denied")
                await insert(app["application_id"], app["full_name"], accord, manual, "agree", week, None,
                             f"Both agreed — loan {manual}.", 0.93 if good else 0.88)

            # period agreement rate
            agree = await conn.fetchval("SELECT count(*) FROM comparison_decisions WHERE tenant_id=$1 AND agreement='agree'", TID)
            total = await conn.fetchval("SELECT count(*) FROM comparison_decisions WHERE tenant_id=$1", TID)
            await conn.execute("UPDATE comparison_periods SET agreement_rate=$1 WHERE period_id=$2", round(agree / total * 100, 1), period_id)

        print(f"Seeded comparison period (day 22 of 90) + {total} decisions for summit; agreement {round(agree / total * 100, 1)}%")
        by = await conn.fetch("SELECT agreement, count(*) FROM comparison_decisions WHERE tenant_id=$1 GROUP BY agreement", TID)
        print("  by agreement:", {r["agreement"]: r["count"] for r in by})
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())

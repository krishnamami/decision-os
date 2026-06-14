"""Seed realistic loan_actions for Summit fraud loans so the Similar Cases panel
and the decision-notes thread have data. Idempotent per application_id."""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

import asyncpg
from dotenv import load_dotenv

SEED_ACTIONS = [
    {"action_type": "refer_bsa", "reason_category": "fraud_concern",
     "reason_text": "Fraud score 0.79 with identity match below threshold. Mandatory BSA referral per policy. Filed SAR investigation.",
     "related_decision_id": "fraud_screening"},
    {"action_type": "deny", "reason_category": "fraud_concern",
     "reason_text": "Fraud score 0.84 confirmed after additional ID review. Identity synthetic — SSN mismatch with IRS records. Denied per BSA recommendation.",
     "related_decision_id": "fraud_screening"},
    {"action_type": "request_documents", "reason_category": "documentation_gap",
     "reason_text": "Fraud score 0.76 borderline. Requested government-issued photo ID resubmission before BSA referral. Giving borrower 48hrs.",
     "related_decision_id": "fraud_screening"},
    {"action_type": "senior_review", "reason_category": "income_exception",
     "reason_text": "Self-employed borrower, income reconciliation partial. 14 months history vs 24 month requirement. Escalating for senior judgment on exception.",
     "related_decision_id": "income_verification"},
    {"action_type": "approve", "reason_category": "credit_exception",
     "reason_text": "DTI borderline at 44.2% but compensating factors strong — 24 months reserves, credit score 748, low LTV 65%. Approved with condition.",
     "related_decision_id": "dti_calculation"},
]


async def main(commit: bool) -> None:
    load_dotenv()
    url = os.environ["DATABASE_URL"].replace("+asyncpg", "").replace("postgresql+psycopg2", "postgresql")
    c = await asyncpg.connect(url)
    try:
        # Distinct Summit loans that have a fraud-screening decision, paired with a
        # plausible reviewer (one per loan).
        loans = await c.fetch(
            """
            SELECT d.application_id,
                   (SELECT u.email FROM users u
                    WHERE u.tenant_id='summit' AND u.role IN ('underwriter','senior_uw','compliance')
                    ORDER BY u.role LIMIT 1) AS email
            FROM decision_outputs d
            WHERE d.tenant_id='summit' AND d.decision_id='fraud_screening' AND d.superseded_by IS NULL
            GROUP BY d.application_id
            ORDER BY d.application_id
            LIMIT 20
            """
        )
        print(f"Found {len(loans)} Summit loans with fraud screening")
        now = datetime.now(timezone.utc)
        to_insert = []
        for i, loan in enumerate(loans[: len(SEED_ACTIONS)]):
            a = SEED_ACTIONS[i % len(SEED_ACTIONS)]
            exists = await c.fetchval("SELECT COUNT(*) FROM loan_actions WHERE application_id=$1", loan["application_id"])
            if exists:
                continue
            to_insert.append((loan["application_id"], a, loan["email"], now - timedelta(days=i * 2)))

        print(f"Mode: {'COMMIT' if commit else 'DRY-RUN'} | rows to insert: {len(to_insert)}")
        for app_id, a, email, when in to_insert[:3]:
            print(f"  {app_id} | {a['action_type']} by {email} | {a['reason_text'][:50]}...")
        if not commit:
            print("DRY-RUN — re-run with --commit to insert.")
            return

        for app_id, a, email, when in to_insert:
            await c.execute(
                """INSERT INTO loan_actions
                   (application_id, tenant_id, action_type, reason_category, reason_text,
                    performed_by, performed_at, related_decision_id, visible_to)
                   VALUES ($1,'summit',$2,$3,$4,$5,$6,$7,$8)""",
                app_id, a["action_type"], a["reason_category"], a["reason_text"],
                email, when, a["related_decision_id"], ["senior_uw", "compliance", "examiner", "bsa"],
            )
        total = await c.fetchval("SELECT COUNT(*) FROM loan_actions WHERE tenant_id='summit'")
        print(f"Inserted {len(to_insert)}. Total Summit loan_actions: {total}")
    finally:
        await c.close()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main("--commit" in sys.argv))

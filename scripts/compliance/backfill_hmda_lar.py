"""RA-7C population job — hmda_lar from underwriting_decision outputs.

Reads CURRENT underwriting_decision outputs (EVERY application — HMDA reports
all actions, not just denials) and the LAR record the persona wrote
(context_snapshot.output_payload.hmda_lar), and upserts one hmda_lar row per
application. action_taken_date is filled from the decision's decided_at.
Idempotent (UNIQUE on application_id+tenant_id).

Writes ONLY to hmda_lar — never touches decision_outputs or any persona/eval
data. Safe to re-run. Default tenant: meridian.

    python scripts/compliance/backfill_hmda_lar.py [tenant]
"""
import asyncio
import json
import os
import sys

from dotenv import load_dotenv

load_dotenv()


def _url():
    return (os.environ["DATABASE_URL"]
            .replace("+asyncpg", "").replace("postgresql+psycopg2", "postgresql"))


def _payload(snapshot):
    snap = json.loads(snapshot) if isinstance(snapshot, str) else (snapshot or {})
    return snap.get("output_payload", snap) if isinstance(snap, dict) else {}


async def main(tenant: str):
    import asyncpg
    conn = await asyncpg.connect(_url())
    rows = await conn.fetch(
        """
        SELECT d.application_id, d.tenant_id, d.context_snapshot,
               d.decided_at::date AS action_date
        FROM decision_outputs d
        WHERE d.tenant_id = $1 AND d.decision_id = 'underwriting_decision'
          AND d.version = (SELECT MAX(version) FROM decision_outputs d2
                           WHERE d2.application_id = d.application_id
                             AND d2.tenant_id = d.tenant_id
                             AND d2.decision_id = d.decision_id)
        ORDER BY d.application_id
        """,
        tenant,
    )

    written = 0
    skipped = 0
    by_action: dict[int, int] = {}
    for r in rows:
        lar = _payload(r["context_snapshot"]).get("hmda_lar")
        if not lar:
            skipped += 1
            continue
        by_action[lar["action_taken"]] = by_action.get(lar["action_taken"], 0) + 1
        await conn.execute(
            """
            INSERT INTO hmda_lar (
                application_id, tenant_id, action_taken, action_taken_date,
                loan_type, loan_purpose, loan_amount, interest_rate,
                loan_term_months, property_type, occupancy_type, state_code,
                county_code, census_tract, lien_status, applicant_income,
                applicant_ethnicity, applicant_race, applicant_sex, applicant_age,
                denial_reasons, aus_result, aus_system, hmda_reportable)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,
                    $17,$18,$19,$20,$21,$22,$23,$24)
            ON CONFLICT (application_id, tenant_id) DO UPDATE SET
                action_taken=EXCLUDED.action_taken,
                action_taken_date=EXCLUDED.action_taken_date,
                loan_amount=EXCLUDED.loan_amount,
                applicant_income=EXCLUDED.applicant_income,
                denial_reasons=EXCLUDED.denial_reasons
            """,
            lar["application_id"], r["tenant_id"], lar["action_taken"], r["action_date"],
            lar.get("loan_type"), lar.get("loan_purpose"), lar.get("loan_amount"),
            lar.get("interest_rate"), lar.get("loan_term_months"),
            lar.get("property_type"), lar.get("occupancy_type"), lar.get("state_code"),
            lar.get("county_code"), lar.get("census_tract"), lar.get("lien_status"),
            lar.get("applicant_income"), lar.get("applicant_ethnicity"),
            lar.get("applicant_race"), lar.get("applicant_sex"), lar.get("applicant_age"),
            lar.get("denial_reasons"), lar.get("aus_result"), lar.get("aus_system"),
            lar.get("hmda_reportable", True),
        )
        written += 1

    print(f"upserted {written} HMDA LAR records ({skipped} had no hmda_lar payload) "
          f"for tenant={tenant!r}")
    labels = {1: "originated", 2: "approved/not-accepted", 3: "denied",
              4: "withdrawn", 5: "incomplete"}
    for code in sorted(by_action):
        print(f"  action_taken {code} ({labels.get(code, '?')}): {by_action[code]}")
    await conn.close()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "meridian"))

"""RA-7B population job — adverse_action_notices from declined decisions.

Reads CURRENT underwriting_decision outputs with outcome='block' and the
adverse-action payload the persona wrote (context_snapshot.output_payload
.adverse_action), and upserts one adverse_action_notices row per declined
application. Idempotent (ON CONFLICT on the app+tenant+decision unique index).

Writes ONLY to adverse_action_notices — never touches decision_outputs or any
persona/eval data. Safe to re-run. Default tenant: meridian (the demo set);
pass a tenant as argv[1] to target another.

    python scripts/compliance/backfill_adverse_action_notices.py [tenant]
"""
import asyncio
import json
import os
import sys
from datetime import datetime

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
        SELECT d.id, d.application_id, d.tenant_id, d.context_snapshot
        FROM decision_outputs d
        WHERE d.tenant_id = $1 AND d.decision_id = 'underwriting_decision'
          AND d.outcome = 'block'
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
    for r in rows:
        aa = _payload(r["context_snapshot"]).get("adverse_action")
        if not aa or not aa.get("hmda_denial_codes"):
            skipped += 1
            continue
        deadline = datetime.fromisoformat(aa["notice_deadline"])
        await conn.execute(
            """
            INSERT INTO adverse_action_notices
                (application_id, tenant_id, decision_id, notice_deadline,
                 hmda_codes, denial_reasons, status)
            VALUES ($1,$2,$3,$4,$5,$6::jsonb,'pending')
            ON CONFLICT (application_id, tenant_id, decision_id) DO UPDATE SET
                notice_deadline = EXCLUDED.notice_deadline,
                hmda_codes      = EXCLUDED.hmda_codes,
                denial_reasons  = EXCLUDED.denial_reasons
            """,
            r["application_id"], r["tenant_id"], r["id"], deadline,
            aa["hmda_denial_codes"], json.dumps(aa["denial_reasons"]),
        )
        written += 1
        print(f"  {r['application_id']}: codes={aa['hmda_denial_codes']} "
              f"deadline={aa['notice_deadline']}")

    print(f"\nupserted {written} adverse-action notices "
          f"({skipped} declines had no adverse_action payload) for tenant={tenant!r}")
    await conn.close()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "meridian"))

"""EX-C population job — loan_exceptions + compensating_factors from the
approval_routing exception_analysis / compensating_factors_analysis that the
persona already emitted (context_snapshot.output_payload).

Reads CURRENT approval_routing decision_outputs and calls
exception_writer.populate_exception_records for each (idempotent per
decision_output). Writes ONLY to loan_exceptions + compensating_factors — never
touches decision_outputs or any eval data. Same pattern as
backfill_adverse_action_notices. Default tenant: meridian.

    python scripts/compliance/backfill_exception_records.py [tenant]
"""
import asyncio
import os
import sys
from dotenv import load_dotenv
load_dotenv()

# Allow running as a standalone script (scripts/compliance/) — put repo root on path.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.exceptions.exception_writer import populate_exception_records


def _url():
    return (os.environ["DATABASE_URL"]
            .replace("+asyncpg", "").replace("postgresql+psycopg2", "postgresql"))


async def main(tenant: str):
    import asyncpg
    conn = await asyncpg.connect(_url())
    try:
        rows = await conn.fetch(
            """SELECT d.id, d.application_id
               FROM decision_outputs d
               WHERE d.tenant_id = $1 AND d.decision_id = 'approval_routing'
                 AND d.version = (SELECT MAX(version) FROM decision_outputs d2
                                  WHERE d2.application_id = d.application_id
                                    AND d2.tenant_id = d.tenant_id
                                    AND d2.decision_id = d.decision_id)
               ORDER BY d.application_id""",
            tenant,
        )
        created = 0
        apps_with = 0
        for r in rows:
            res = await populate_exception_records(
                conn, r["application_id"], tenant, r["id"])
            if res.get("written"):
                apps_with += 1
                created += res.get("exceptions_created", 0)
                print(f"  {r['application_id']}: {res['exceptions_created']} exception(s), "
                      f"level={res.get('approval_level')} score={res.get('exception_score')}")
        print(f"\nwrote {created} loan_exceptions across {apps_with}/{len(rows)} "
              f"approval_routing decisions for tenant={tenant!r}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "meridian"))

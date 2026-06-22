"""
Backfill fraud_indicator fact_nodes across the meridian tenant (RA-3E).

There is no live resolver orchestrator in the runtime (the 4 existing fact
types were batch-populated the same way), so this script:
  1. runs the fraud detectors (idempotent — they skip apps already signalled),
  2. runs FraudFactResolver per app to emit a fraud_indicator fact_node for any
     app with fraud signals.

Clean loans get no fact_node. Re-runnable (save_fact_node supersedes).

  python scripts/evidence/backfill_fraud_facts.py
"""
import asyncio
import os
import sys
from dotenv import load_dotenv
load_dotenv()
sys.path.insert(0, ".")

TENANT = "meridian"


def _u():
    return os.environ["DATABASE_URL"].replace("+asyncpg", "").replace(
        "postgresql+psycopg2", "postgresql")


async def main():
    import asyncpg
    from core.fraud.income_mismatch_detector import IncomeMismatchDetector
    from core.fraud.undisclosed_debt_detector import UndisclosedDebtDetector
    from core.evidence.resolvers import FraudFactResolver

    conn = await asyncpg.connect(_u())
    try:
        apps = [r["application_id"] for r in await conn.fetch(
            "SELECT DISTINCT application_id FROM entity_states "
            "WHERE tenant_id=$1 ORDER BY application_id", TENANT)]

        imd = IncomeMismatchDetector(conn)
        udd = UndisclosedDebtDetector(conn)
        resolver = FraudFactResolver(conn)

        print(f"Backfilling fraud facts for {len(apps)} apps\n")
        emitted = 0
        for app in apps:
            # 1. ensure detectors have run (idempotent — dedup inside)
            try:
                await imd.detect(app, TENANT)
                await udd.detect(app, TENANT)
            except Exception as exc:  # noqa: BLE001
                print(f"  ! {app}: detector error {exc}")

            # 2. resolve fraud_indicator fact from the signals
            facts = await resolver.resolve(app, TENANT)
            if facts:
                f = facts["fraud_indicator"]
                emitted += 1
                print(f"  + {app}: fraud_indicator conf={f.confidence} "
                      f"value={f.fact_value} method={f.resolution_method}")
            else:
                print(f"  - {app}: no fraud signals")

        print(f"\nEmitted {emitted} fraud_indicator fact_node(s).")

        # Verify
        print("\n=== current fraud_indicator facts ===")
        for r in await conn.fetch(
            "SELECT application_id, fact_value, confidence, conflicts_found, "
            "resolution_method FROM fact_nodes "
            "WHERE tenant_id=$1 AND fact_type='fraud_indicator' "
            "AND superseded_by IS NULL ORDER BY confidence DESC", TENANT):
            print(f"  {r['application_id']}: value={r['fact_value']} "
                  f"conf={r['confidence']} conflicts={r['conflicts_found']} "
                  f"method={r['resolution_method']}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())

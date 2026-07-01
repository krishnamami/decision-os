"""READ ONLY — list CHECK constraints on the tables the Step 4 fixture inserts,
so we pick valid enum values. No mutations."""
import asyncio
import os

TABLES = ["entity_states", "decision_trace", "fraud_signals",
          "loan_condition_instances", "property_eligibility"]


async def main():
    import asyncpg
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    for t in TABLES:
        rows = await conn.fetch(
            """SELECT con.conname, pg_get_constraintdef(con.oid) AS def
               FROM pg_constraint con
               JOIN pg_class c ON c.oid = con.conrelid
               JOIN pg_namespace n ON n.oid = c.relnamespace
               WHERE n.nspname='public' AND c.relname=$1 AND con.contype='c'
               ORDER BY con.conname""", t)
        print(f"\n=== CHECK constraints: {t} ===")
        if not rows:
            print("  (none)")
        for r in rows:
            print(f"  {r['conname']}: {r['def']}")
    await conn.close()


asyncio.run(main())

"""QA-C Step 4 — READ ONLY schema introspection to author the isolation test.
Columns / NOT NULL / defaults + FKs for entity_states and the 4 UPDATE tables,
plus candidate view definitions for check (e). No mutations."""
import asyncio
import os

TABLES = ["entity_states", "decision_trace", "fraud_signals",
          "loan_condition_instances", "property_eligibility"]
VIEWS = ["vw_pipeline_status", "vw_fraud_screening_context"]


async def main():
    import asyncpg
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])

    for t in TABLES:
        print(f"\n=== columns: {t} ===")
        cols = await conn.fetch(
            """SELECT column_name, data_type, is_nullable, column_default
               FROM information_schema.columns
               WHERE table_schema='public' AND table_name=$1
               ORDER BY ordinal_position""", t)
        for c in cols:
            print(f"  {c['column_name']:<26} {c['data_type']:<28} "
                  f"null={c['is_nullable']:<3} default={c['column_default']}")
        print(f"  -- NOT NULL, no-default columns (must be supplied on INSERT):")
        req = [c['column_name'] for c in cols
               if c['is_nullable'] == 'NO' and not c['column_default']]
        print("   ", req)

    print("\n=== foreign keys on those tables ===")
    fks = await conn.fetch(
        """SELECT tc.table_name, kcu.column_name,
                  ccu.table_name AS ref_table, ccu.column_name AS ref_col
           FROM information_schema.table_constraints tc
           JOIN information_schema.key_column_usage kcu
             ON tc.constraint_name=kcu.constraint_name AND tc.table_schema=kcu.table_schema
           JOIN information_schema.constraint_column_usage ccu
             ON tc.constraint_name=ccu.constraint_name AND tc.table_schema=ccu.table_schema
           WHERE tc.constraint_type='FOREIGN KEY' AND tc.table_schema='public'
             AND tc.table_name = ANY($1::text[])
           ORDER BY tc.table_name, kcu.column_name""", TABLES)
    if not fks:
        print("  (none)")
    for f in fks:
        print(f"  {f['table_name']}.{f['column_name']} -> {f['ref_table']}.{f['ref_col']}")

    for v in VIEWS:
        print(f"\n=== view def: {v} ===")
        try:
            print(await conn.fetchval("SELECT pg_get_viewdef($1::regclass, true)", f"public.{v}"))
        except Exception as e:  # noqa: BLE001
            print("  (error)", repr(e))

    await conn.close()


asyncio.run(main())

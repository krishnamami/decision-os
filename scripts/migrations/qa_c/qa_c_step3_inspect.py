"""QA-C Step 3 — READ ONLY inspection. Reports:
  - PG version (security_invoker needs >= 15)
  - vw_* views: owner + reloptions (is security_invoker already set?)
  - every policy referencing CURRENT_USER (USING or WITH CHECK)
No mutations. Runs as edms_admin via DATABASE_URL already in the task def."""
import asyncio
import os


async def main():
    import asyncpg
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])

    print("=== PG version ===")
    print(await conn.fetchval("SELECT version()"))

    print("\n=== vw_* views (name | owner | reloptions) ===")
    rows = await conn.fetch(
        r"""SELECT c.relname AS view, pg_get_userbyid(c.relowner) AS owner, c.reloptions
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relkind = 'v' AND n.nspname = 'public' AND c.relname LIKE 'vw\_%'
            ORDER BY c.relname""")
    for r in rows:
        print(dict(r))
    print(f"(total {len(rows)} vw_* views)")

    print("\n=== ALL views in public (name | owner | security_invoker?) ===")
    allv = await conn.fetch(
        """SELECT c.relname AS view, pg_get_userbyid(c.relowner) AS owner,
                  (c.reloptions::text) AS reloptions
           FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
           WHERE c.relkind = 'v' AND n.nspname = 'public'
           ORDER BY c.relname""")
    for r in allv:
        print(dict(r))
    print(f"(total {len(allv)} views in public)")

    print("\n=== policies referencing CURRENT_USER ===")
    pols = await conn.fetch(
        """SELECT tablename, policyname, cmd, qual, with_check
           FROM pg_policies
           WHERE schemaname = 'public'
             AND (coalesce(qual, '') ILIKE '%current_user%'
                  OR coalesce(with_check, '') ILIKE '%current_user%')
           ORDER BY tablename, policyname""")
    for p in pols:
        print(f"[{p['tablename']}] {p['policyname']} | cmd={p['cmd']}")
        print("   USING:     ", p["qual"])
        if p["with_check"] is not None:
            print("   WITH CHECK:", p["with_check"])
    print(f"(total {len(pols)} policies referencing CURRENT_USER)")

    await conn.close()


asyncio.run(main())

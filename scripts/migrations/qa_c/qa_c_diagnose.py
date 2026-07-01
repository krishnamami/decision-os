"""QA-C diagnosis — READ ONLY. Confirms edms_admin bypassrls makes RLS inert.
Loads DATABASE_URL from .env; never prints the password."""
import asyncio
import os
import re
from dotenv import load_dotenv

load_dotenv()


def _mask(url: str) -> str:
    return re.sub(r"://([^:]+):[^@]+@", r"://\1:***@", url or "")


async def main():
    url = os.environ["DATABASE_URL"]
    print("=== Connection string (masked) ===")
    print(_mask(url))

    import asyncpg
    conn = await asyncpg.connect(url)

    roles = await conn.fetch("""
        SELECT rolname, rolsuper, rolinherit, rolbypassrls, rolcanlogin
        FROM pg_roles
        WHERE rolname IN ('edms_admin', 'accord_app', 'postgres')
        ORDER BY rolname
    """)
    print("\n=== Current roles ===")
    for r in roles:
        print(dict(r))

    current = await conn.fetchrow("SELECT current_user, session_user")
    print("\n=== Current connection role ===", dict(current))

    policies = await conn.fetchrow("SELECT count(*) AS policy_count FROM pg_policies")
    print("\n=== RLS policy count ===", dict(policies))

    rls_tables = await conn.fetch("""
        SELECT tablename, rowsecurity
        FROM pg_tables
        WHERE schemaname = 'public' AND rowsecurity = true
        ORDER BY tablename
    """)
    print(f"\n=== Tables with RLS enabled ({len(rls_tables)}) ===")
    for t in rls_tables:
        print(t["tablename"])

    tenants = await conn.fetch("""
        SELECT tenant_id, count(*) AS loan_count
        FROM entity_states
        GROUP BY tenant_id
        ORDER BY tenant_id
    """)
    print("\n=== Tenants visible from entity_states (ALL == bypassrls is active) ===")
    for t in tenants:
        print(dict(t))

    pol = await conn.fetch("""
        SELECT tablename, policyname, permissive, roles, cmd, qual, with_check
        FROM pg_policies
        WHERE schemaname = 'public'
        ORDER BY tablename, policyname
    """)
    print(f"\n=== RLS policy definitions ({len(pol)} total) ===")
    for p in pol:
        print(f"[{p['tablename']}] {p['policyname']} | cmd={p['cmd']} "
              f"| roles={p['roles']} | permissive={p['permissive']}")
        print(f"    USING:      {p['qual']}")
        if p["with_check"] is not None:
            print(f"    WITH CHECK: {p['with_check']}")

    await conn.close()


asyncio.run(main())

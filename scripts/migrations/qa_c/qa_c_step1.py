"""QA-C Step 1 — provision accord_app as a usable least-privilege LOGIN role.

Runs INSIDE the VPC as edms_admin (via DATABASE_URL already in the task def).
Reads the new password from ACCORD_APP_PWD (ECS env override) and quotes it with
Postgres format(%L) — no string interpolation, no echo. All DDL runs in one
transaction (all-or-nothing). Prints verification only; never the password.

No app behaviour changes here: the API still connects as edms_admin until Step 5.
"""
import asyncio
import os

# 1b–1f exactly as shown/approved. 1a is built separately with %L quoting.
DDL_STMTS = [
    # 1b — connect + schema usage
    "GRANT CONNECT ON DATABASE edms TO accord_app",
    "GRANT USAGE ON SCHEMA public TO accord_app",
    # 1c — full DML on all current tables/views
    "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO accord_app",
    # 1d — sequences
    "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO accord_app",
    # 1e — preserve governance boundary (shared catalogue read-only for accord_app)
    "REVOKE INSERT, UPDATE, DELETE ON regulatory_rules, agency_guidelines FROM accord_app",
    # 1f — future objects created by edms_admin inherit the grants
    "ALTER DEFAULT PRIVILEGES FOR ROLE edms_admin IN SCHEMA public "
    "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO accord_app",
    "ALTER DEFAULT PRIVILEGES FOR ROLE edms_admin IN SCHEMA public "
    "GRANT USAGE, SELECT ON SEQUENCES TO accord_app",
]


async def main():
    import asyncpg
    url = os.environ["DATABASE_URL"]
    pwd = os.environ.get("ACCORD_APP_PWD")
    if not pwd:
        print("FATAL: ACCORD_APP_PWD not present in container env")
        raise SystemExit(2)

    conn = await asyncpg.connect(url)
    try:
        async with conn.transaction():
            # 1a — inject password via safe %L literal quoting (injection-proof)
            alter = await conn.fetchval(
                "SELECT format('ALTER ROLE accord_app WITH LOGIN PASSWORD %L', $1::text)", pwd)
            await conn.execute(alter)
            for s in DDL_STMTS:
                await conn.execute(s)
        print("Step 1 DDL committed OK.\n")
    except Exception as e:  # noqa: BLE001
        print("Step 1 DDL FAILED — transaction rolled back:", repr(e))
        await conn.close()
        raise SystemExit(1)

    # ---- verification (read-only) ----
    r = await conn.fetchrow(
        "SELECT rolname, rolcanlogin, rolbypassrls, rolsuper "
        "FROM pg_roles WHERE rolname='accord_app'")
    print("=== accord_app role attributes (expect canlogin=t, bypassrls=f, super=f) ===")
    print(dict(r))

    n = await conn.fetchval(
        "SELECT count(*) FROM information_schema.role_table_grants "
        "WHERE grantee='accord_app' AND table_schema='public'")
    print("\n=== granted table-privilege rows for accord_app (public) ===")
    print(n)

    gov = await conn.fetch(
        "SELECT table_name, privilege_type FROM information_schema.role_table_grants "
        "WHERE grantee='accord_app' AND table_name IN ('regulatory_rules','agency_guidelines') "
        "ORDER BY table_name, privilege_type")
    print("\n=== governance tables (expect SELECT only — no INSERT/UPDATE/DELETE) ===")
    for g in gov:
        print(dict(g))

    await conn.close()

    # ---- login test as accord_app (proves the LOGIN + password work) ----
    print("\n=== login test: connect as accord_app ===")
    try:
        c2 = await asyncpg.connect(url, user="accord_app", password=pwd)
        who = await c2.fetchrow("SELECT current_user, session_user")
        print("connected OK:", dict(who))
        await c2.close()
    except Exception as e:  # noqa: BLE001
        print("LOGIN TEST FAILED:", repr(e))
        raise SystemExit(1)


asyncio.run(main())

"""Run the Accord auth/multi-tenancy migration against EDMS PG.

  python scripts/migrations/run_auth_migration.py            # tables + seed (safe, additive)
  python scripts/migrations/run_auth_migration.py --retenant # ALSO move data 'default' -> 'demo'

The runner bcrypt-hashes the seed password ('accord2026') in place of the
HASH_IN_CODE placeholder in create_auth_tables.sql. The @RETENANT block is
stripped unless --retenant is given (it is destructive — see the .sql).
"""

import asyncio
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Import the project's bcrypt helper.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from core.auth.security import hash_password  # noqa: E402

SEED_PASSWORD = "accord2026"
SQL_PATH = Path(__file__).with_name("create_auth_tables.sql")


def build_sql(retenant: bool) -> str:
    sql = SQL_PATH.read_text(encoding="utf-8")
    # Replace the password placeholder with a real bcrypt hash (one hash for
    # all four seed users — they share the same password).
    sql = sql.replace("HASH_IN_CODE", hash_password(SEED_PASSWORD))
    if not retenant:
        sql = re.sub(r"-- @RETENANT_START.*?-- @RETENANT_END", "-- (re-tenant block skipped)", sql, flags=re.DOTALL)
    return sql


async def main(retenant: bool) -> None:
    import asyncpg

    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL not set")

    conn = await asyncpg.connect(url)
    try:
        await conn.execute(build_sql(retenant))

        tenants = await conn.fetch("SELECT tenant_id, name, plan, products FROM tenants ORDER BY tenant_id")
        users = await conn.fetch("SELECT email, name, role FROM users ORDER BY role, email")
        print("Migration applied.")
        print(f"  tenants ({len(tenants)}):")
        for t in tenants:
            print(f"    {t['tenant_id']:8s} {t['name']:14s} plan={t['plan']:10s} products={t['products']}")
        print(f"  users ({len(users)}):")
        for u in users:
            print(f"    {u['email']:22s} {u['name']:18s} {u['role']}")

        if retenant:
            dist = await conn.fetch("SELECT tenant_id, count(*) FROM entity_states GROUP BY tenant_id")
            print("  entity_states by tenant:", [(r["tenant_id"], r["count"]) for r in dist])
        else:
            print("  (re-tenant step skipped — data stays under tenant 'default')")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main("--retenant" in sys.argv))

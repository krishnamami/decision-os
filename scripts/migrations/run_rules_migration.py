"""Apply the Rules Dashboard migration (create_rules_tables.sql).

  python scripts/migrations/run_rules_migration.py

Additive and idempotent (CREATE TABLE / ADD COLUMN IF NOT EXISTS), so it's
safe to re-run. Reads DATABASE_URL from .env like the other migrations.
"""

import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

SQL_PATH = Path(__file__).with_name("create_rules_tables.sql")
TABLES = ["regulatory_rules", "agency_guidelines", "tenant_rules", "data_source_status", "rule_change_alerts"]


async def main() -> None:
    import asyncpg

    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL not set")

    conn = await asyncpg.connect(url)
    try:
        await conn.execute(SQL_PATH.read_text(encoding="utf-8"))
        print("Rules migration applied.")
        for t in TABLES:
            n = await conn.fetchval(f"SELECT count(*) FROM {t}")
            print(f"  {t:22s} rows={n}")
        has_col = await conn.fetchval(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name='decision_outputs' AND column_name='rule_version_id'"
        )
        print(f"  decision_outputs.rule_version_id present={bool(has_col)}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())

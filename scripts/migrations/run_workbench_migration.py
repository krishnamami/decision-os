"""Apply the Accord workbench schema (create_workbench_tables.sql) to EDMS PG.

  python scripts/migrations/run_workbench_migration.py

Additive and idempotent — safe to re-run.
"""

import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

SQL_PATH = Path(__file__).with_name("create_workbench_tables.sql")

TABLES = (
    "loan_assignments",
    "communications",
    "attention_requests",
    "loan_notes",
    "conditions",
    "notifications",
)


async def main() -> None:
    import asyncpg

    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL not set")

    conn = await asyncpg.connect(url)
    try:
        await conn.execute(SQL_PATH.read_text(encoding="utf-8"))
        print("Workbench migration applied.")
        for t in TABLES:
            n = await conn.fetchval(f"SELECT count(*) FROM {t}")
            print(f"  {t:20s} rows={n}")
        cols = await conn.fetch(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'entity_states' "
            "AND column_name IN ('loan_status', 'current_stage', 'assigned_to') "
            "ORDER BY column_name"
        )
        print("  entity_states lifecycle columns:", [c["column_name"] for c in cols])
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())

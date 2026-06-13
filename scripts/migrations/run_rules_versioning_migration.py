"""Apply the rules-versioning migration (create_rules_versioning.sql).

  python scripts/migrations/run_rules_versioning_migration.py

Additive + idempotent. Reads DATABASE_URL from .env.
"""

import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

SQL_PATH = Path(__file__).with_name("create_rules_versioning.sql")
TABLES = ["shadow_evaluations", "examination_periods", "rescreen_events", "retrospective_analyses"]
NEW_COLS = ["change_type", "scheduled_for", "expires_at", "rolled_back_from", "pipeline_policy",
            "ratified_by", "channel", "shadow_duration_days", "emergency_type"]


async def main() -> None:
    import asyncpg

    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL not set")
    conn = await asyncpg.connect(url)
    try:
        await conn.execute(SQL_PATH.read_text(encoding="utf-8"))
        print("Rules-versioning migration applied.")
        for t in TABLES:
            n = await conn.fetchval(f"SELECT count(*) FROM {t}")
            print(f"  {t:24s} rows={n}")
        cols = await conn.fetch(
            "SELECT column_name FROM information_schema.columns WHERE table_name='tenant_rules' AND column_name = ANY($1::text[])",
            NEW_COLS)
        print(f"  tenant_rules new cols: {sorted(c['column_name'] for c in cols)}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())

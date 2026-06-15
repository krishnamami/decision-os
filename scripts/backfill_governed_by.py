"""Backfill decision_outputs.governed_by from decisions.yaml governance.

For each (decision_id, outcome) that has governing citations in decisions.yaml,
stamp them on the matching decision_outputs rows where governed_by IS NULL.
Idempotent — only NULL rows are written.
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()


def _url() -> str:
    raw = os.environ["DATABASE_URL"]
    return raw.replace("+asyncpg", "").replace("postgresql+psycopg2", "postgresql")


async def main() -> None:
    import asyncpg  # type: ignore

    from domains.lending.governance import _gov_map

    gov = _gov_map()  # {(decision_id, outcome): [governed_by...]}
    conn = await asyncpg.connect(_url())
    try:
        before = await conn.fetchval(
            "SELECT COUNT(*) FROM decision_outputs WHERE governed_by IS NOT NULL")
        total = 0
        for (decision_id, outcome), govs in gov.items():
            res = await conn.execute(
                """
                UPDATE decision_outputs
                SET governed_by = $1::jsonb
                WHERE decision_id = $2 AND outcome = $3 AND governed_by IS NULL
                """,
                json.dumps(govs), decision_id, outcome,
            )
            n = int(res.split()[-1]) if res.startswith("UPDATE") else 0
            if n:
                total += n
                print(f"  {decision_id}/{outcome}: {n} rows ({len(govs)} citations)")
        after = await conn.fetchval(
            "SELECT COUNT(*) FROM decision_outputs WHERE governed_by IS NOT NULL")
        print(f"Backfill: +{total} rows. governed_by populated: {before} -> {after}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())

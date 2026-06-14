"""Backfill decision_outputs.rule_version_id where it is NULL.

For each decision with a NULL rule_version_id, find the tenant_rules version
that was active (or superseded — i.e. in force at the time) for that tenant at
the decision's decided_at, most-recent version winning. Tenants with no
tenant_rules (e.g. 'demo') are left NULL — that is correct.

Set-based and idempotent: only NULL rows are touched, and re-running is a no-op
once populated. Safe to run multiple times.

The decided_at (timestamptz) is normalised to naive UTC before comparing
against tenant_rules.effective_from/effective_to (naive UTC), matching the
write-path lookup in core/decision_store.py.
"""
import asyncio
import os

from dotenv import load_dotenv

load_dotenv()


def _url() -> str:
    raw = os.environ["DATABASE_URL"]
    return raw.replace("+asyncpg", "").replace("postgresql+psycopg2", "postgresql")


async def main() -> None:
    import asyncpg  # type: ignore

    conn = await asyncpg.connect(_url())
    try:
        before = await conn.fetchrow(
            """
            SELECT COUNT(*) FILTER (WHERE rule_version_id IS NULL) AS nulls,
                   COUNT(*) AS total
            FROM decision_outputs
            """
        )
        print(f"Before: {before['nulls']} NULL of {before['total']} total")

        result = await conn.execute(
            """
            WITH matched AS (
                SELECT dout.id,
                       (
                         SELECT tr.rule_version_id
                         FROM tenant_rules tr
                         WHERE tr.tenant_id = dout.tenant_id
                           AND tr.status IN ('active', 'superseded')
                           AND tr.effective_from <= (dout.decided_at AT TIME ZONE 'UTC')
                           AND (tr.effective_to IS NULL
                                OR tr.effective_to > (dout.decided_at AT TIME ZONE 'UTC'))
                         ORDER BY tr.version DESC
                         LIMIT 1
                       ) AS rvid
                FROM decision_outputs dout
                WHERE dout.rule_version_id IS NULL
                  AND dout.tenant_id IS NOT NULL
                  AND dout.decided_at IS NOT NULL
            )
            UPDATE decision_outputs d
            SET rule_version_id = m.rvid
            FROM matched m
            WHERE d.id = m.id
              AND m.rvid IS NOT NULL
            """
        )
        # result is like "UPDATE 1858"
        print(f"Backfill: {result}")

        after = await conn.fetchrow(
            """
            SELECT COUNT(*) FILTER (WHERE rule_version_id IS NOT NULL) AS populated,
                   COUNT(*) FILTER (WHERE rule_version_id IS NULL) AS nulls,
                   COUNT(*) AS total
            FROM decision_outputs
            """
        )
        print(f"After: {after['populated']} populated, {after['nulls']} NULL of {after['total']} total")

        per_tenant = await conn.fetch(
            """
            SELECT tenant_id,
                   COUNT(*) FILTER (WHERE rule_version_id IS NOT NULL) AS populated,
                   COUNT(*) FILTER (WHERE rule_version_id IS NULL) AS nulls
            FROM decision_outputs
            GROUP BY tenant_id
            ORDER BY tenant_id
            """
        )
        print("Per tenant (populated / null):")
        for r in per_tenant:
            print(f"  {r['tenant_id']}: {r['populated']} / {r['nulls']}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())

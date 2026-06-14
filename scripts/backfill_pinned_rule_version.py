"""Backfill rain-check fields on entity_states.

1. application_date — from applications.created_at where NULL.
2. pinned_rule_version / pinned_at — for rate-locked loans with no pin, pin to
   the tenant_rules version that was in force (active or superseded) at the
   loan's lock date (application_date, else applications.created_at).

Set-based and idempotent: only NULL fields are written; tenants with no rules
(e.g. 'demo') leave pins NULL by design. Safe to re-run.

tenant_rules.effective_from/effective_to are naive timestamps; the comparison
is done on ::date so it lines up with the date-typed application_date.
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
            SELECT COUNT(*) FILTER (WHERE application_date IS NOT NULL) AS has_appdate,
                   COUNT(*) FILTER (WHERE rate_locked AND pinned_rule_version IS NOT NULL) AS pinned_locked,
                   COUNT(*) FILTER (WHERE rate_locked) AS locked,
                   COUNT(*) AS total
            FROM entity_states
            """
        )
        print(f"Before: app_date={before['has_appdate']}, "
              f"pinned_locked={before['pinned_locked']}/{before['locked']} locked, total={before['total']}")

        # 1. application_date from applications.created_at
        r1 = await conn.execute(
            """
            UPDATE entity_states es
            SET application_date = a.created_at::date
            FROM applications a
            WHERE a.application_id = es.application_id
              AND es.application_date IS NULL
            """
        )
        print(f"application_date backfill: {r1}")

        # 2. Pin rate-locked, unpinned loans to the version in force at lock date.
        r2 = await conn.execute(
            """
            WITH locked AS (
                SELECT es.application_id, es.tenant_id,
                       COALESCE(es.application_date, a.created_at::date) AS lock_date
                FROM entity_states es
                JOIN applications a ON a.application_id = es.application_id
                WHERE es.rate_locked = true
                  AND es.pinned_rule_version IS NULL
            ), resolved AS (
                SELECT l.application_id, l.lock_date,
                       (
                         SELECT tr.rule_version_id
                         FROM tenant_rules tr
                         WHERE tr.tenant_id = l.tenant_id
                           AND tr.status IN ('active', 'superseded')
                           AND tr.effective_from::date <= l.lock_date
                           AND (tr.effective_to IS NULL OR tr.effective_to::date > l.lock_date)
                         ORDER BY tr.version DESC
                         LIMIT 1
                       ) AS rvid
                FROM locked l
            )
            UPDATE entity_states e
            SET pinned_rule_version = resolved.rvid,
                pinned_at = COALESCE(e.pinned_at, resolved.lock_date::timestamp)
            FROM resolved
            WHERE e.application_id = resolved.application_id
              AND resolved.rvid IS NOT NULL
            """
        )
        print(f"pin backfill: {r2}")

        after = await conn.fetchrow(
            """
            SELECT COUNT(*) FILTER (WHERE application_date IS NOT NULL) AS has_appdate,
                   COUNT(*) FILTER (WHERE rate_locked AND pinned_rule_version IS NOT NULL) AS pinned_locked,
                   COUNT(*) FILTER (WHERE rate_locked AND pinned_rule_version IS NULL) AS unpinned_locked,
                   COUNT(*) FILTER (WHERE rate_locked) AS locked,
                   COUNT(*) AS total
            FROM entity_states
            """
        )
        print(f"After: app_date={after['has_appdate']}, "
              f"pinned_locked={after['pinned_locked']}, unpinned_locked={after['unpinned_locked']}, "
              f"locked={after['locked']}, total={after['total']}")

        per_tenant = await conn.fetch(
            """
            SELECT tenant_id,
                   COUNT(*) FILTER (WHERE rate_locked) AS locked,
                   COUNT(*) FILTER (WHERE rate_locked AND pinned_rule_version IS NOT NULL) AS pinned
            FROM entity_states GROUP BY tenant_id ORDER BY tenant_id
            """
        )
        print("Per tenant (pinned / locked):")
        for r in per_tenant:
            print(f"  {r['tenant_id']}: {r['pinned']} / {r['locked']}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())

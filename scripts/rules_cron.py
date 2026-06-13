"""Rules-versioning scheduled jobs (Part 4).

  python scripts/rules_cron.py            # run all four jobs once
  python scripts/rules_cron.py scheduled  # run one job

A scheduler (cron / ECS scheduled task / GitHub Action) invokes this. Each job
is idempotent and safe to run repeatedly. Reads DATABASE_URL from .env.

Jobs:
  scheduled  — activate tenant_rules whose scheduled_for has arrived
  emergency  — auto-revert emergency changes not ratified within 24h
  expiration — deactivate rules past expires_at; flag expiring waivers
  shadow     — close shadow tests whose duration has elapsed
"""

import asyncio
import os
import sys
from datetime import datetime, timedelta

from dotenv import load_dotenv

load_dotenv()


async def activate_scheduled(conn) -> int:
    rows = await conn.fetch("SELECT * FROM tenant_rules WHERE status='scheduled' AND scheduled_for <= NOW()")
    n = 0
    for r in rows:
        async with conn.transaction():
            await conn.execute("UPDATE tenant_rules SET status='superseded', effective_to=NOW() WHERE tenant_id=$1 AND status='active'", r["tenant_id"])
            await conn.execute("UPDATE tenant_rules SET status='active', effective_from=NOW() WHERE rule_version_id=$1", r["rule_version_id"])
        print(f"  activated scheduled v{r['version']} for {r['tenant_id']}")
        n += 1
    return n


async def revert_unratified_emergencies(conn) -> int:
    cutoff = datetime.utcnow() - timedelta(hours=24)
    rows = await conn.fetch(
        "SELECT * FROM tenant_rules WHERE change_type='emergency' AND status='active' AND ratified_by IS NULL AND created_at < $1",
        cutoff)
    n = 0
    for r in rows:
        async with conn.transaction():
            await conn.execute("UPDATE tenant_rules SET status='superseded', effective_to=NOW() WHERE rule_version_id=$1", r["rule_version_id"])
            prev = await conn.fetchrow(
                "SELECT * FROM tenant_rules WHERE tenant_id=$1 AND status='superseded' AND version < $2 ORDER BY version DESC LIMIT 1",
                r["tenant_id"], r["version"])
            if prev:
                await conn.execute("UPDATE tenant_rules SET status='active', effective_to=NULL WHERE rule_version_id=$1", prev["rule_version_id"])
        print(f"  auto-reverted un-ratified emergency v{r['version']} for {r['tenant_id']}")
        n += 1
    return n


async def expire_rules(conn) -> int:
    rows = await conn.fetch("SELECT * FROM tenant_rules WHERE expires_at IS NOT NULL AND expires_at <= NOW() AND status IN ('active','shadow')")
    n = 0
    for r in rows:
        await conn.execute("UPDATE tenant_rules SET status='superseded', effective_to=NOW() WHERE rule_version_id=$1", r["rule_version_id"])
        print(f"  expired v{r['version']} ({r['status']}) for {r['tenant_id']}")
        n += 1
    # Waiver-expiry warnings (30/7/1 day marks) — surfaced via GET /rules.expiring.
    return n


async def complete_shadows(conn) -> int:
    rows = await conn.fetch("SELECT * FROM tenant_rules WHERE status='shadow' AND expires_at IS NOT NULL AND expires_at <= NOW()")
    n = 0
    for r in rows:
        diffs = await conn.fetchval("SELECT count(*) FROM shadow_evaluations WHERE shadow_version=$1 AND difference IS NOT NULL", r["version"])
        await conn.execute("UPDATE tenant_rules SET status='superseded' WHERE rule_version_id=$1", r["rule_version_id"])
        print(f"  shadow v{r['version']} for {r['tenant_id']} complete — {diffs} loans would have changed (report ready)")
        n += 1
    return n


JOBS = {
    "scheduled": activate_scheduled,
    "emergency": revert_unratified_emergencies,
    "expiration": expire_rules,
    "shadow": complete_shadows,
}


async def main(only: str | None) -> None:
    import asyncpg

    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL not set")
    conn = await asyncpg.connect(url)
    try:
        jobs = {only: JOBS[only]} if only in JOBS else JOBS
        for name, fn in jobs.items():
            print(f"[{name}]")
            count = await fn(conn)
            print(f"  -> {count} affected")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else None))

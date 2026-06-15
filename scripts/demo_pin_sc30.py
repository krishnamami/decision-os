"""Demo helper — pin/unpin APP-SC30-004 so the rain-check badge shows
"protected" in the demo video (pinned to summit rule v1, current is v3).

  python scripts/demo_pin_sc30.py          # pin to v1 + rate_locked (protected)
  python scripts/demo_pin_sc30.py --unpin  # restore original state

Reversible — APP-SC30-004 starts unpinned + unlocked, so --unpin returns it
exactly to its original state.

UNDO SQL (run after demo recording):
  UPDATE entity_states
  SET pinned_rule_version = NULL, pinned_at = NULL, rate_locked = false
  WHERE application_id = 'APP-SC30-004';
"""
import argparse
import asyncio
import os
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

APP = "APP-SC30-004"
TENANT = "summit"
PINNED_AT = datetime(2026, 2, 1)  # within summit v1's window (2026-01-01 .. 2026-03-15)


def _url() -> str:
    raw = os.environ["DATABASE_URL"]
    return raw.replace("+asyncpg", "").replace("postgresql+psycopg2", "postgresql")


async def main(unpin: bool) -> None:
    import asyncpg
    conn = await asyncpg.connect(_url())
    try:
        if unpin:
            await conn.execute(
                "UPDATE entity_states SET pinned_rule_version=NULL, pinned_at=NULL, rate_locked=false "
                "WHERE application_id=$1 AND tenant_id=$2", APP, TENANT)
            print(f"{APP} unpinned (pinned_rule_version=NULL, rate_locked=false).")
        else:
            v1 = await conn.fetchval(
                "SELECT rule_version_id FROM tenant_rules WHERE tenant_id=$1 AND version=1", TENANT)
            if v1 is None:
                raise SystemExit("summit rule v1 not found")
            await conn.execute(
                "UPDATE entity_states SET pinned_rule_version=$1, pinned_at=$2, rate_locked=true "
                "WHERE application_id=$3 AND tenant_id=$4", v1, PINNED_AT, APP, TENANT)
            print(f"{APP} pinned to summit rule v1 ({v1}) at {PINNED_AT}, rate_locked=true — protected vs current v3.")
        row = await conn.fetchrow(
            "SELECT es.rate_locked, tr.version AS pinned_v, cur.version AS current_v, es.pinned_at "
            "FROM entity_states es "
            "LEFT JOIN tenant_rules tr ON tr.rule_version_id = es.pinned_rule_version "
            "LEFT JOIN tenant_rules cur ON cur.tenant_id = es.tenant_id AND cur.status='active' "
            "WHERE es.application_id=$1 AND es.tenant_id=$2", APP, TENANT)
        print(f"  now: rate_locked={row['rate_locked']} pinned_v={row['pinned_v']} current_v={row['current_v']} pinned_at={row['pinned_at']}")
    finally:
        await conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--unpin", action="store_true", help="restore (clear the pin)")
    args = ap.parse_args()
    asyncio.run(main(args.unpin))

#!/usr/bin/env python
"""Pre-flight check for the demo recording — is the tenant's data camera-ready?

  python scripts/demo_data_check.py            # checks the 'summit' tenant
  python scripts/demo_data_check.py pacific    # checks another tenant
  DEMO_TENANT=summit python scripts/demo_data_check.py

The demo (docs/DEMO_SCRIPT.md) is recorded as processor1@summit.com, so the
relevant data lives under tenant_id='summit'. This verifies the moments the
script relies on actually exist:

  * >= 3 active loans in the processor queue
  * >= 1 fraud-blocked loan        (fraud_screening = block)
  * >= 1 income-blocked loan       (income_verification = block)
  * >= 1 clean loan                (all checks ran, nothing blocked)
  * >= 1 pre-run MiroFish debate
  * >= 1 pre-run simulation
  * >= 1 pre-run swarm

Prints "✅ Demo data ready" or "❌ Missing: ..." and exits non-zero if not
ready, so it can gate a recording session. Reads DATABASE_URL from .env, same
as the rest of the repo.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:  # keep ✅/❌ alive on a Windows console
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

import asyncpg  # noqa: E402

# How to fix each missing piece — surfaced in the report so the run is actionable.
FIX = {
    "debate": "python scripts/mirofish.py debate APP-SC02-001",
    "simulation": 'python scripts/mirofish.py simulate --scenario "DTI threshold: 43% -> 36%"',
    "swarm": "python scripts/mirofish.py swarm",
    "loans": "python scripts/migrations/seed_tenants_and_users.py",
}


async def _count(conn, sql: str, *args) -> int:
    """Run a COUNT, treating a missing table as zero (engines not migrated yet)."""
    try:
        val = await conn.fetchval(sql, *args)
        return int(val or 0)
    except asyncpg.UndefinedTableError:
        return 0


async def main() -> int:
    tenant = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("DEMO_TENANT", "summit")).strip()
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("❌ DATABASE_URL not set (check your .env)")
        return 2

    conn = await asyncpg.connect(url)
    try:
        active_in_queue = await _count(
            conn,
            "SELECT count(*) FROM entity_states "
            "WHERE tenant_id=$1 AND loan_status='active' AND assigned_to IS NOT NULL",
            tenant,
        )
        fraud_blocked = await _count(
            conn,
            "SELECT count(DISTINCT application_id) FROM decision_outputs "
            "WHERE tenant_id=$1 AND decision_id='fraud_screening' AND outcome='block'",
            tenant,
        )
        income_blocked = await _count(
            conn,
            "SELECT count(DISTINCT application_id) FROM decision_outputs "
            "WHERE tenant_id=$1 AND decision_id='income_verification' AND outcome='block'",
            tenant,
        )
        # Clean = every check ran (>= 6 decisions) and none blocked.
        clean = await _count(
            conn,
            "SELECT count(*) FROM ("
            "  SELECT application_id FROM decision_outputs WHERE tenant_id=$1"
            "  GROUP BY application_id"
            "  HAVING bool_or(outcome='block') = false AND count(*) >= 6"
            ") t",
            tenant,
        )
        debates = await _count(conn, "SELECT count(*) FROM mirofish_debates WHERE tenant_id=$1", tenant)
        sims = await _count(conn, "SELECT count(*) FROM mirofish_simulations WHERE tenant_id=$1", tenant)
        swarms = await _count(conn, "SELECT count(*) FROM mirofish_swarm_runs WHERE tenant_id=$1", tenant)
    finally:
        await conn.close()

    # (label, value, threshold, fix-key)
    checks = [
        ("Active loans in processor queue", active_in_queue, 3, "loans"),
        ("Fraud-blocked loan", fraud_blocked, 1, "loans"),
        ("Income-blocked loan", income_blocked, 1, "loans"),
        ("Clean loan (all passed)", clean, 1, "loans"),
        ("Pre-run MiroFish debate", debates, 1, "debate"),
        ("Pre-run simulation", sims, 1, "simulation"),
        ("Pre-run swarm", swarms, 1, "swarm"),
    ]

    print(f"\nDemo data check — tenant '{tenant}'")
    print("─" * 52)
    missing: list[tuple[str, str]] = []
    for label, value, need, fix in checks:
        ok = value >= need
        print(f"  {'✅' if ok else '❌'}  {label:<34} {value:>4}  (need {need}+)")
        if not ok:
            missing.append((label, FIX[fix]))

    print("─" * 52)
    if not missing:
        print("✅ Demo data ready\n")
        return 0

    print("❌ Missing: " + ", ".join(label for label, _ in missing))
    print("\n  To fix:")
    for label, fix in dict((m[0], m[1]) for m in missing).items():
        print(f"    • {label:<34} {fix}")
    print()
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

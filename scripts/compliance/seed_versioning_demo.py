"""Seed Summit's versioning demo history (Part 5).

  python scripts/compliance/seed_versioning_demo.py

Rebuilds summit's tenant_rules into v1→v2→v3 (+ scheduled v4), adds a First-Time
Homebuyer waiver expiring 2026-09-30 to the active v3, and pins a handful of
summit loans to older versions so the loan-detail "rules note" demonstrates a
version mismatch. ONLY touches the 'summit' tenant. Idempotent (delete + reinsert).
"""

import asyncio
import json
import os
from datetime import date, datetime

from dotenv import load_dotenv

load_dotenv()

TID = "summit"


def overlay(credit: int, dti_back: int, ltv_max: int, waivers: list | None = None) -> dict:
    o = {
        "credit": {"min_score": credit, "prime_threshold": 700},
        "dti": {"front_max": 28, "back_max": dti_back, "review_band": [36, dti_back]},
        "ltv": {"max": ltv_max, "no_mi_threshold": 80, "jumbo_max": 85},
        "reserves": {"primary": 2, "investment": 6},
        "fraud": {"watchlist_threshold": 0.20, "identity_min": 0.85},
        "income": {"max_discrepancy_pct": 25, "review_band_pct": [10, 25]},
        "programs": ["conventional", "fha", "va"],
    }
    if waivers:
        o["waivers"] = waivers
    return o


WAIVER = [{"name": "First-Time Homebuyer", "field": "credit floor", "value": 620, "normal": 640, "expires": "2026-09-30"}]


async def main() -> None:
    import asyncpg

    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL not set")
    conn = await asyncpg.connect(url)
    try:
        admin = await conn.fetchval("SELECT user_id FROM users WHERE tenant_id=$1 AND role='admin' LIMIT 1", TID)
        async with conn.transaction():
            await conn.execute("DELETE FROM tenant_rules WHERE tenant_id=$1", TID)

            async def insert(version, status, rules, summary, reason, eff_from, eff_to,
                             change_type="standard", scheduled_for=None, programs=None):
                return await conn.fetchval(
                    "INSERT INTO tenant_rules (tenant_id, version, status, rules, programs, changes_summary, change_reason, "
                    " created_by, approved_by, effective_from, effective_to, approved_at, change_type, scheduled_for, pipeline_policy) "
                    "VALUES ($1,$2,$3,$4::jsonb,$5::jsonb,$6,$7,$8,$8,$9,$10,$9,$11,$12,'grandfather') RETURNING rule_version_id",
                    TID, version, status, json.dumps(rules), json.dumps(programs or ["conventional", "fha", "va"]),
                    summary, reason, admin, eff_from, eff_to, change_type, scheduled_for,
                )

            v1 = await insert(1, "superseded", overlay(620, 45, 97), "Initial rules", "Initial onboarding configuration",
                              datetime(2026, 1, 1), datetime(2026, 3, 15))
            v2 = await insert(2, "superseded", overlay(640, 45, 97), "Credit floor 620 → 640",
                              "Aligning with internal risk committee recommendation",
                              datetime(2026, 3, 15), datetime(2026, 5, 1))
            v3 = await insert(3, "active", overlay(640, 43, 97, WAIVER), "DTI 45% → 43%",
                              "QM alignment — want all loans within safe harbor",
                              datetime(2026, 5, 1), None)
            await insert(4, "scheduled", overlay(640, 43, 95), "LTV 97% → 95%", "Q3 risk reduction",
                         None, None, change_type="scheduled", scheduled_for=datetime(2026, 7, 1))

        # Pin some summit loans to older versions (so a loan shows a rules-note mismatch).
        apps = [r["application_id"] for r in await conn.fetch(
            "SELECT application_id FROM entity_states WHERE tenant_id=$1 ORDER BY application_id LIMIT 30", TID)]
        plan = [(apps[0:3], v1, date(2026, 2, 1)), (apps[3:8], v2, date(2026, 4, 1)), (apps[8:], v3, date(2026, 5, 15))]
        pinned = 0
        for group, ver, app_date in plan:
            for app in group:
                await conn.execute(
                    "UPDATE entity_states SET pinned_rule_version=$1, pinned_at=NOW(), application_date=$2 "
                    "WHERE application_id=$3 AND tenant_id=$4",
                    ver, app_date, app, TID)
                pinned += 1

        rows = await conn.fetch("SELECT version, status, change_type FROM tenant_rules WHERE tenant_id=$1 ORDER BY version", TID)
        print("summit versions:", [(r["version"], r["status"], r["change_type"]) for r in rows])
        print(f"pinned {pinned} loans (3 to v1, 5 to v2, rest to v3); v3 carries the FTHB waiver (expires 2026-09-30)")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())

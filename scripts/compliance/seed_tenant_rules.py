"""Seed version 1 of each tenant's customer overlay rules (🔧 adjustable layer).

  python scripts/compliance/seed_tenant_rules.py

Idempotent: only creates v1 for a tenant that has NO rule versions yet, so it
never clobbers edits made through the dashboard. Reads DATABASE_URL from .env.
"""

import asyncio
import json
import os

from dotenv import load_dotenv

load_dotenv()

# tenant_id → overlay rules
OVERLAYS: dict[str, dict] = {
    "summit": {  # conservative mid-size lender
        "credit": {"min_score": 640, "prime_threshold": 700},
        "dti": {"front_max": 28, "back_max": 43, "review_band": [36, 43]},
        "ltv": {"max": 95, "no_mi_threshold": 80, "jumbo_max": 85},
        "reserves": {"primary": 2, "investment": 6},
        "fraud": {"watchlist_threshold": 0.20, "identity_min": 0.85},
        "income": {"max_discrepancy_pct": 25, "review_band_pct": [10, 25]},
        "programs": ["conventional", "fha", "va"],
    },
    "pacific": {  # aggressive, higher risk tolerance
        "credit": {"min_score": 620, "prime_threshold": 680},
        "dti": {"front_max": 31, "back_max": 50, "review_band": [43, 50]},
        "ltv": {"max": 97, "no_mi_threshold": 80, "jumbo_max": 90},
        "reserves": {"primary": 0, "investment": 6},
        "fraud": {"watchlist_threshold": 0.25, "identity_min": 0.80},
        "income": {"max_discrepancy_pct": 30, "review_band_pct": [15, 30]},
        "programs": ["conventional", "fha", "jumbo", "non_qm"],
    },
    "heartland": {  # conservative credit union
        "credit": {"min_score": 660, "prime_threshold": 720},
        "dti": {"front_max": 28, "back_max": 41, "review_band": [33, 41]},
        "ltv": {"max": 90, "no_mi_threshold": 80, "jumbo_max": 80},
        "reserves": {"primary": 3, "investment": 8},
        "fraud": {"watchlist_threshold": 0.15, "identity_min": 0.90},
        "income": {"max_discrepancy_pct": 20, "review_band_pct": [5, 20]},
        "programs": ["conventional", "fha", "va", "usda"],
    },
    "atlas": {  # jumbo specialist
        "credit": {"min_score": 700, "prime_threshold": 740},
        "dti": {"front_max": 28, "back_max": 38, "review_band": [33, 38]},
        "ltv": {"max": 85, "no_mi_threshold": 75, "jumbo_max": 80},
        "reserves": {"primary": 6, "investment": 12},
        "fraud": {"watchlist_threshold": 0.15, "identity_min": 0.90},
        "income": {"max_discrepancy_pct": 15, "review_band_pct": [5, 15]},
        "programs": ["conventional", "jumbo", "non_qm"],
    },
}


async def main() -> None:
    import asyncpg

    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL not set")
    conn = await asyncpg.connect(url)
    seeded, skipped = [], []
    try:
        for tid, overlay in OVERLAYS.items():
            existing = await conn.fetchval("SELECT count(*) FROM tenant_rules WHERE tenant_id=$1", tid)
            if existing:
                skipped.append(tid)
                continue
            admin_id = await conn.fetchval("SELECT user_id FROM users WHERE tenant_id=$1 AND role='admin' LIMIT 1", tid)
            programs = overlay.get("programs", ["conventional", "fha"])
            await conn.execute(
                "INSERT INTO tenant_rules "
                "(tenant_id, version, status, rules, programs, changes_summary, change_reason, "
                " created_by, approved_by, effective_from, approved_at) "
                "VALUES ($1, 1, 'active', $2::jsonb, $3::jsonb, $4, $5, $6, $6, TIMESTAMP '2026-04-01', TIMESTAMP '2026-04-01')",
                tid, json.dumps(overlay), json.dumps(programs),
                "Initial rules (Accord defaults customized for tenant)",
                "Initial onboarding configuration", admin_id,
            )
            seeded.append(tid)
        print(f"Seeded v1 for: {seeded or '(none)'}")
        if skipped:
            print(f"Skipped (already have versions): {skipped}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())

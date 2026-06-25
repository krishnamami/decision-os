"""CI-B — seed a synthetic meridian tenant_rules v2 (DRAFT) for cross-version replay.

Meridian has only ONE rule version (v1, active), so there is nothing to replay
"v1 vs v2" against. This seeds a second version that differs in two thresholds:

    credit.min_score   640 -> 680   (stricter)
    dti.back_max        43 ->  40   (stricter)

v2 is a "tighter credit box". On this dataset the credit delta flips no outcome
(all non-blocked apps score >680; the sub-640 apps already block), while the DTI
delta flips the three loans sitting at dti 42.0 (SC07/SC14/SC16) -> block. (The
original spec proposed dti 43->45 looser, but nothing on meridian sits in (43,45],
so it was a no-op; 40 produces a demonstrable, honest cross-version flip.)

CRITICAL: v2 is seeded with status='draft', NOT 'active'. The live decision path
resolves the *active* version (v1), so the meridian decisions + 16/16 are
UNCHANGED. The replay engine targets v2 explicitly by rule_version_id, which
ThresholdResolver reads regardless of status — so replay works while v1 stays live.

Idempotent: if a meridian v2 already exists, its rules are refreshed in place and
its existing rule_version_id is reused (so the id stays stable across re-runs).

    PYTHONIOENCODING=utf-8 PYTHONUTF8=1 python scripts/compliance/seed_ci_b_v2_rules.py
"""
import asyncio
import copy
import json
import os
import sys

from dotenv import load_dotenv

load_dotenv()

TENANT = "meridian"
V2 = 2
# The deltas that make v2 a distinct, demonstrable version.
V2_CHANGES = {
    ("credit", "min_score"): 680,   # 640 -> 680 (stricter)
    ("dti", "back_max"): 40,        # 43 -> 40 (stricter — flips the 42% apps)
}


def _u():
    return os.environ["DATABASE_URL"].replace("+asyncpg", "").replace(
        "postgresql+psycopg2", "postgresql")


def _apply_changes(rules: dict) -> dict:
    out = copy.deepcopy(rules) if isinstance(rules, dict) else {}
    for (cat, field), val in V2_CHANGES.items():
        out.setdefault(cat, {})
        if isinstance(out[cat], dict):
            out[cat][field] = val
    return out


async def main():
    import asyncpg
    conn = await asyncpg.connect(_u())
    try:
        v1 = await conn.fetchrow(
            "SELECT rule_version_id, rules, programs FROM tenant_rules "
            "WHERE tenant_id=$1 AND status='active' ORDER BY version DESC LIMIT 1",
            TENANT)
        if not v1:
            print(f"FATAL: no active tenant_rules for {TENANT}; nothing to base v2 on.")
            return
        v1_rules = v1["rules"]
        if isinstance(v1_rules, str):
            v1_rules = json.loads(v1_rules)
        v2_rules = _apply_changes(v1_rules)

        existing = await conn.fetchrow(
            "SELECT rule_version_id, status FROM tenant_rules "
            "WHERE tenant_id=$1 AND version=$2", TENANT, V2)

        if existing:
            await conn.execute(
                "UPDATE tenant_rules SET rules=$1::jsonb, changes_summary=$2, "
                "change_reason=$3 WHERE tenant_id=$4 AND version=$5",
                json.dumps(v2_rules),
                "CI-B synthetic v2: credit 640->680, dti 43->40 (both stricter)",
                "CI-B cross-version replay demo", TENANT, V2)
            rid = existing["rule_version_id"]
            print(f"v2 already existed (status={existing['status']}) — rules refreshed in place.")
        else:
            row = await conn.fetchrow(
                "INSERT INTO tenant_rules (tenant_id, version, status, rules, programs, "
                "changes_summary, change_reason, effective_from) "
                "VALUES ($1,$2,'draft',$3::jsonb,$4::jsonb,$5,$6,NULL) "
                "RETURNING rule_version_id",
                TENANT, V2, json.dumps(v2_rules),
                json.dumps(["conventional", "fha"]),
                "CI-B synthetic v2: credit 640->680, dti 43->40 (both stricter)",
                "CI-B cross-version replay demo")
            rid = row["rule_version_id"]
            print("v2 inserted (status=draft — NOT active; live path still resolves v1).")

        # Verify: show both versions side by side.
        print(f"\nmeridian v2 rule_version_id = {rid}")
        rows = await conn.fetch(
            "SELECT version, status, rule_version_id, "
            "rules->'credit'->>'min_score' AS credit_min, "
            "rules->'dti'->>'back_max' AS dti_max "
            "FROM tenant_rules WHERE tenant_id=$1 ORDER BY version", TENANT)
        print("\nversion  status   credit.min_score  dti.back_max  rule_version_id")
        for r in rows:
            print(f"  v{r['version']:<5} {r['status']:<8} {str(r['credit_min']):<17} "
                  f"{str(r['dti_max']):<13} {r['rule_version_id']}")
        # Confirm v1 is still the sole ACTIVE version (16/16 safety).
        active = await conn.fetch(
            "SELECT version FROM tenant_rules WHERE tenant_id=$1 AND status='active'", TENANT)
        print(f"\nactive versions: {[r['version'] for r in active]} "
              f"(must be [1] — v2 is draft, decision path unchanged)")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())

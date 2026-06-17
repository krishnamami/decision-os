"""Seed ONLY the Decision-OS-owned data for the meridian tenant (PROMPT IJ-B / Part 1).

EDMS already loaded applications / entity_states / document_index / the tenants
row into RDS. This script adds only what Decision OS owns:

  - tenant_rules v1 (active) + a first-time-homebuyer credit-floor waiver
  - 5 users (password: accord2026)
  - 9 rate_sheet_entry rows
  - 9 products (creating a USDA authority/program where missing)
  - pins APP-MRID-SC07 to rule v1 (rain check)

It does NOT seed applications / entity_states / documents (EDMS owns those).
Idempotent — safe to re-run.

  python scripts/seed_meridian_tenant.py
"""
import asyncio
import json
import os
import uuid
from datetime import date, datetime

from dotenv import load_dotenv

load_dotenv()

TENANT = "meridian"

# tenant_rules.rules — same nested structure the evaluator + ThresholdResolver
# actually read (credit.min_score, dti.back_max, ltv.max, reserves.primary, …),
# NOT flat keys. Values are Meridian's baseline policy.
RULES = {
    "credit": {"min_score": 640, "prime_threshold": 700},
    "dti": {"back_max": 43, "front_max": 28, "review_band": [36, 43]},
    "ltv": {"max": 97, "jumbo_max": 85, "no_mi_threshold": 80},
    "fraud": {"identity_min": 0.85, "watchlist_threshold": 0.2},
    "income": {"max_discrepancy_pct": 25, "review_band_pct": [10, 25]},
    "reserves": {"primary": 2, "investment": 6},
    "max_loan_amount": 2000000,
    "first_time_buyer_credit_floor": 620,
    # Surfaced in Policy Studio's expiring-waivers + as documentation of the FTB
    # credit-floor override required for SC06 (Priya Sharma, credit 627).
    "waivers": [{
        "name": "First-Time Homebuyer", "field": "credit floor",
        "value": 620, "normal": 640, "expires": "2026-09-30",
    }],
}
PROGRAMS = ["conventional", "fha", "va", "usda"]

# (email, name, role) — role strings are the app's real roles (senior_uw, not
# "senior_underwriter", so role-based nav resolves).
USERS = [
    ("admin@meridian.com", "Admin User", "admin"),
    ("underwriter@meridian.com", "Sarah Chen", "underwriter"),
    ("compliance@meridian.com", "Mark Rivera", "compliance"),
    ("senioruw@meridian.com", "Karen Whitfield", "senior_uw"),
    ("manager@meridian.com", "James Porter", "manager"),
]

# product_id, name, program_id, rate_type, short_code, conforming_limit (doc only)
PRODUCTS = [
    ("PRD-MRID-CONF30", "Meridian Conforming 30yr Fixed", "PGM-FNMA-PURCH", "Fixed", "CONF30"),
    ("PRD-MRID-CONF15", "Meridian Conforming 15yr Fixed", "PGM-FNMA-PURCH", "Fixed", "CONF15"),
    ("PRD-MRID-HB30", "Meridian High Balance 30yr", "PGM-FNMA-PURCH", "Fixed", "HB30"),
    ("PRD-MRID-FHA30", "Meridian FHA 30yr Fixed", "PGM-FHA-PURCH", "Fixed", "FHA30"),
    ("PRD-MRID-FHA15", "Meridian FHA 15yr Fixed", "PGM-FHA-PURCH", "Fixed", "FHA15"),
    ("PRD-MRID-VA30", "Meridian VA 30yr Fixed", "PGM-VA-PURCH", "Fixed", "VA30"),
    ("PRD-MRID-VA15", "Meridian VA 15yr Fixed", "PGM-VA-PURCH", "Fixed", "VA15"),
    ("PRD-MRID-USDA", "Meridian USDA Rural", "PGM-USDA-PURCH", "Fixed", "USDA"),
    ("PRD-MRID-JUMBO30", "Meridian Jumbo 30yr Fixed", "PGM-NONQM-PURCH", "Fixed", "JUMBO30"),
]

# Rate sheet — product_id, credit_band, ltv_max, base_rate, llpa_adjustment.
# Score-range bands per the spec (9 distinct rows).
RATES = [
    ("PRD-MRID-CONF30", "760-999", 80, 6.500, 0.000),
    ("PRD-MRID-CONF30", "740-759", 80, 6.625, 0.250),
    ("PRD-MRID-CONF30", "720-739", 80, 6.750, 0.500),
    ("PRD-MRID-CONF30", "700-719", 80, 6.875, 0.625),
    ("PRD-MRID-CONF30", "680-699", 80, 7.125, 0.875),
    ("PRD-MRID-CONF30", "660-679", 80, 7.375, 1.125),
    ("PRD-MRID-CONF30", "640-659", 80, 7.625, 1.375),
    ("PRD-MRID-FHA30", "580-999", 96.5, 7.125, 0.000),
    ("PRD-MRID-VA30", "620-999", 100, 6.875, 0.000),
]


def _u(): return os.environ["DATABASE_URL"].replace("+asyncpg", "").replace("postgresql+psycopg2", "postgresql")


async def main():
    import asyncpg
    conn = await asyncpg.connect(_u())
    try:
        # 0. tenants row — EDMS should have created it; ensure it exists.
        has_tenant = await conn.fetchval("SELECT 1 FROM tenants WHERE tenant_id=$1", TENANT)
        print(f"tenants row: {'exists' if has_tenant else 'MISSING'}")

        # 1. tenant_rules v1 (active)
        existing_v1 = await conn.fetchrow(
            "SELECT rule_version_id FROM tenant_rules WHERE tenant_id=$1 AND version=1", TENANT)
        if existing_v1:
            rule_version_id = existing_v1["rule_version_id"]
            print(f"tenant_rules v1 already present ({rule_version_id})")
        else:
            rule_version_id = uuid.uuid4()
            await conn.execute(
                """INSERT INTO tenant_rules
                     (rule_version_id, tenant_id, version, status, rules, programs,
                      changes_summary, change_reason, effective_from, approved_at, created_at, change_type)
                   VALUES ($1,$2,1,'active',$3::jsonb,$4::jsonb,
                           'Meridian baseline policy','Initial seed',
                           TIMESTAMP '2026-01-01', NOW(), NOW(), 'standard')""",
                rule_version_id, TENANT, json.dumps(RULES), json.dumps(PROGRAMS))
            print(f"tenant_rules v1 created ({rule_version_id})")

        # 2. users (copy a bcrypt hash for 'accord2026' from an existing user)
        pw_hash = await conn.fetchval(
            "SELECT password_hash FROM users WHERE password_hash LIKE '$2%' LIMIT 1")
        if not pw_hash:
            raise SystemExit("No bcrypt password_hash found to copy for accord2026")
        admin_uid = None
        created_users = 0
        for email, name, role in USERS:
            row = await conn.fetchrow("SELECT user_id FROM users WHERE email=$1", email)
            if row:
                uid = row["user_id"]
            else:
                uid = await conn.fetchval(
                    """INSERT INTO users (tenant_id, email, password_hash, name, role, is_active, created_at, updated_at)
                       VALUES ($1,$2,$3,$4,$5,true,NOW(),NOW()) RETURNING user_id""",
                    TENANT, email, pw_hash, name, role)
                created_users += 1
            if role == "admin":
                admin_uid = uid
        print(f"users: {created_users} created (5 total expected)")

        # 3. USDA authority + program (only if missing) so the USDA product lists.
        if not await conn.fetchval("SELECT 1 FROM governing_authority WHERE governing_authority_id='GA-USDA'"):
            await conn.execute(
                """INSERT INTO governing_authority
                     (governing_authority_id, governing_authority_key, authority_name, short_code,
                      authority_type, loan_type_classification, guideline_set_reference, active_indicator,
                      mers_eligible_indicator, enote_accepted_indicator, per_diem_day_count_basis,
                      effective_start_date, workspace_id, tenant_id)
                   VALUES ('GA-USDA','GA-USDA-KEY','United States Department of Agriculture','USDA',
                           'Agency','Government','USDA Rural Dev Handbook 2026', true,
                           true, true, 'Actual365', TIMESTAMPTZ '2025-01-01', 'default','default')""")
            print("governing_authority GA-USDA created")
        if not await conn.fetchval("SELECT 1 FROM program WHERE program_id='PGM-USDA-PURCH'"):
            await conn.execute(
                """INSERT INTO program
                     (program_id, program_key, program_name, governing_authority_id, product_category_id,
                      loan_purpose, available_rate_types, active_indicator, effective_start_date,
                      workspace_id, tenant_id)
                   VALUES ('PGM-USDA-PURCH','PGM-USDA-PURCH-KEY','USDA Rural Development Purchase','GA-USDA',
                           'CAT-GOVT','Purchase','Both', true, TIMESTAMPTZ '2025-01-01','default','default')""")
            print("program PGM-USDA-PURCH created")

        # 4. products
        created_products = 0
        for pid, pname, prog, rate_type, short in PRODUCTS:
            if await conn.fetchval("SELECT 1 FROM product WHERE product_id=$1", pid):
                continue
            await conn.execute(
                """INSERT INTO product
                     (product_id, product_key, program_id, product_name, short_code,
                      rate_type, active_indicator, effective_start_date, workspace_id, tenant_id)
                   VALUES ($1,$2,$3,$4,$5,$6,true, TIMESTAMPTZ '2026-01-01','default',$7)""",
                pid, pid + "-KEY", prog, pname, short, rate_type, TENANT)
            created_products += 1
        print(f"products: {created_products} created (9 total expected)")

        # 5. rate sheet — clear meridian rows first so a re-run yields exactly 9.
        await conn.execute("DELETE FROM rate_sheet_entry WHERE tenant_id=$1", TENANT)
        created_rates = 0
        for pid, band, ltv, base, llpa in RATES:
            r = await conn.execute(
                """INSERT INTO rate_sheet_entry
                     (tenant_id, product_id, credit_band, ltv_max, base_rate, llpa_adjustment,
                      effective_date, uploaded_by, uploaded_at)
                   VALUES ($1,$2,$3,$4,$5,$6,DATE '2026-01-01',$7,NOW())
                   ON CONFLICT (tenant_id, product_id, credit_band, ltv_max, effective_date) DO NOTHING""",
                TENANT, pid, band, ltv, base, llpa, admin_uid)
            if r.endswith(" 1"):
                created_rates += 1
        print(f"rate_sheet_entry: {created_rates} created (9 expected; dupes skipped)")

        # 6. Rain check — pin APP-MRID-SC07 to rule v1.
        await conn.execute(
            """UPDATE entity_states
               SET pinned_rule_version=$1, pinned_at=TIMESTAMP '2026-02-01', rate_locked=true
               WHERE application_id='APP-MRID-SC07' AND tenant_id=$2""",
            rule_version_id, TENANT)
        pinned = await conn.fetchval(
            "SELECT pinned_rule_version FROM entity_states WHERE application_id='APP-MRID-SC07' AND tenant_id=$1", TENANT)

        # ── Verify ──
        print("\n=== VERIFY ===")
        print("tenant_rules:", await conn.fetchval("SELECT COUNT(*) FROM tenant_rules WHERE tenant_id=$1", TENANT))
        print("users:", await conn.fetchval("SELECT COUNT(*) FROM users WHERE tenant_id=$1", TENANT))
        print("rate_sheet_entry:", await conn.fetchval("SELECT COUNT(*) FROM rate_sheet_entry WHERE tenant_id=$1", TENANT))
        print("products:", await conn.fetchval("SELECT COUNT(*) FROM product WHERE tenant_id=$1", TENANT))
        print("SC07 pinned to v1:", "confirmed" if str(pinned) == str(rule_version_id) else f"NOT PINNED ({pinned})")
    finally:
        await conn.close()


asyncio.run(main())

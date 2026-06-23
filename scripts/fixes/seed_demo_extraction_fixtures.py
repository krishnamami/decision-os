"""
Seed DEMO-FIXTURE extraction fields into meridian document_index (RA-EX-C demo).

CLIENT-FIRST DEMO ONLY. These values are labelled demo fixtures
(extraction_method='demo_fixture', extracted_fields._demo_fixture=true) so the
golden_record dry-run shows full field coverage end-to-end before a real
extraction pipeline exists. Idempotent / re-runnable.

What it seeds, per meridian application:
  PURCHASE_AGREEMENT  (NEW doc)  purchase_price = entity_states.purchase_price
                                 (the lesser-of value, so golden LTV matches the
                                 seeded LTV — closes the purchase_price + LTV gap),
                                 close_date, seller_concessions, earnest_money,
                                 contract_date.
  BANK_STATEMENT_M1   (augment) large_deposits, nsf_count (statement_date already
                                 present as statement_end_date).
  CREDIT_REPORT       (augment) tradelines array (representative; the live doc
                                 only had tradeline_count).

It does NOT touch entity_states — the seeded scenarios stay intact, so 16/16
holds. apply_golden_record stays write=False on meridian (the SC08 credit
conflict — fixture mid 578 vs doc 760 — means write=True would still break it).

  python scripts/fixes/seed_demo_extraction_fixtures.py
"""
import asyncio
import json
import os
from dotenv import load_dotenv
load_dotenv()

TENANT = "meridian"

# Scenario-coherent large deposits: SC15 is the large-undocumented-deposit case.
LARGE_DEPOSITS = {
    "APP-MRID-SC15": [{"date": "2026-05-18", "amount": 47000.0,
                       "description": "Incoming wire — source not documented"}],
}


def _u():
    return os.environ["DATABASE_URL"].replace("+asyncpg", "").replace(
        "postgresql+psycopg2", "postgresql")


def _sample_tradelines(count: int) -> list:
    """A small representative tradeline array for the demo (the live CREDIT_REPORT
    only carried a count). TradelineAnalyzer reads per-line detail."""
    base = [
        {"creditor_name": "Chase Card", "account_type": "revolving",
         "account_status": "open", "current_balance": 2400.0,
         "credit_limit": 9000.0, "monthly_payment": 75.0,
         "delinquency_30": 0, "delinquency_60": 0, "delinquency_90": 0,
         "dispute_flag": False, "authorized_user": False,
         "reported_date": "2026-05-01"},
        {"creditor_name": "Toyota Financial", "account_type": "installment",
         "account_status": "open", "current_balance": 18500.0,
         "credit_limit": None, "monthly_payment": 410.0,
         "delinquency_30": 0, "delinquency_60": 0, "delinquency_90": 0,
         "dispute_flag": False, "authorized_user": False,
         "reported_date": "2026-04-15"},
    ]
    return base[:max(1, min(count, len(base)))] if count else base


async def main():
    import asyncpg
    c = await asyncpg.connect(_u())
    try:
        apps = await c.fetch(
            "SELECT application_id, applicant_id, purchase_price "
            "FROM entity_states es "
            "LEFT JOIN LATERAL (SELECT applicant_id FROM document_index d "
            "  WHERE d.application_id=es.application_id AND d.tenant_id=es.tenant_id "
            "  LIMIT 1) di ON true "
            "WHERE es.tenant_id=$1 ORDER BY application_id", TENANT)

        pa_seeded = bank_aug = credit_aug = 0
        for r in apps:
            app = r["application_id"]
            applicant = r["applicant_id"] or f"APPLICANT-{app}"
            pp = float(r["purchase_price"] or 0)

            # ── 1. PURCHASE_AGREEMENT (new demo doc) ──────────────────────
            pa_fields = {
                "purchase_price": pp,
                "close_date": "2026-07-15",
                "contract_date": "2026-05-01",
                "seller_concessions_pct": 0.0,
                "seller_concessions_amt": 0.0,
                "earnest_money": round(pp * 0.01, 2),
                "_demo_fixture": True,
            }
            await c.execute(
                """
                INSERT INTO document_index (
                    document_id, applicant_id, application_id, document_type,
                    document_category, borrower_role, status, received_at,
                    is_current, extracted_fields, confidence_score,
                    extraction_method, tenant_id)
                VALUES ($1,$2,$3,'PURCHASE_AGREEMENT','purchase','primary',
                        'processed', NOW(), true, $4::jsonb, 1.0,
                        'demo_fixture', $5)
                ON CONFLICT (document_id) DO UPDATE SET
                    extracted_fields = EXCLUDED.extracted_fields,
                    extraction_method = 'demo_fixture', is_current = true
                """,
                f"DOC-{app}-PURCHASE_AGREEMENT-DEMO", applicant, app,
                json.dumps(pa_fields), TENANT)
            pa_seeded += 1

            # ── 2. augment BANK_STATEMENT_M1 (large_deposits, nsf_count) ──
            row = await c.fetchrow(
                "SELECT extracted_fields FROM document_index WHERE application_id=$1 "
                "AND tenant_id=$2 AND document_type='BANK_STATEMENT_M1' AND is_current=true",
                app, TENANT)
            if row:
                f = row["extracted_fields"]
                f = json.loads(f) if isinstance(f, str) else dict(f or {})
                f["large_deposits"] = LARGE_DEPOSITS.get(app, [])
                f["nsf_count"] = 0
                f["_demo_fixture"] = True
                f["_demo_seeded_fields"] = ["large_deposits", "nsf_count"]
                await c.execute(
                    "UPDATE document_index SET extracted_fields=$1::jsonb "
                    "WHERE application_id=$2 AND tenant_id=$3 "
                    "AND document_type='BANK_STATEMENT_M1' AND is_current=true",
                    json.dumps(f), app, TENANT)
                bank_aug += 1

            # ── 3. augment CREDIT_REPORT (tradelines array) ──────────────
            row = await c.fetchrow(
                "SELECT extracted_fields FROM document_index WHERE application_id=$1 "
                "AND tenant_id=$2 AND document_type='CREDIT_REPORT' AND is_current=true",
                app, TENANT)
            if row:
                f = row["extracted_fields"]
                f = json.loads(f) if isinstance(f, str) else dict(f or {})
                f["tradelines"] = _sample_tradelines(int(f.get("tradeline_count") or 0))
                f["_demo_fixture"] = True
                f["_demo_seeded_fields"] = ["tradelines"]
                await c.execute(
                    "UPDATE document_index SET extracted_fields=$1::jsonb "
                    "WHERE application_id=$2 AND tenant_id=$3 "
                    "AND document_type='CREDIT_REPORT' AND is_current=true",
                    json.dumps(f), app, TENANT)
                credit_aug += 1

        print(f"PURCHASE_AGREEMENT seeded: {pa_seeded}")
        print(f"BANK_STATEMENT_M1 augmented: {bank_aug}")
        print(f"CREDIT_REPORT augmented: {credit_aug}")
    finally:
        await c.close()


if __name__ == "__main__":
    asyncio.run(main())

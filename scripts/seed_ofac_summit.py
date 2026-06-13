"""Seed OFAC_CHECK documents for Summit loans that lack one.

Part A of wiring OFAC screening to be document-traceable. For every Summit loan
(entity_states.tenant_id='summit') with no OFAC_CHECK document, inserts one
document_index row so the existing fraud_screening evidence linkage (which keys
on application_id + the 'identity' category) surfaces a real OFAC source doc.

Schema notes (verified against the live DB, not assumed):
  - document_index PK is document_id; borrower_role is NOT NULL (no default).
  - tenant_id defaults to 'default' (the EDMS shared store); we set it explicitly
    to the loan's own tenant ('summit') per spec. Retrieval (documents API +
    fraud evidence) matches by application_id only, so tenant does not gate it.
  - borrower name lives in applicants.full_name, joined via borrower.applicant_id.

Usage:
    python scripts/seed_ofac_summit.py            # dry-run (default) — inserts nothing
    python scripts/seed_ofac_summit.py --commit   # perform the inserts
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone

import asyncpg
from dotenv import load_dotenv

BATCH = 100
LIST_DATE = "2026-06-12"


def _url() -> str:
    load_dotenv()
    return os.environ["DATABASE_URL"].replace("+asyncpg", "").replace("postgresql+psycopg2", "postgresql")


async def _targets(c: asyncpg.Connection) -> list[dict]:
    rows = await c.fetch(
        """
        SELECT es.application_id,
               es.tenant_id,
               es.borrower->>'applicant_id' AS applicant_id,
               COALESCE(a.full_name,
                        NULLIF(TRIM(CONCAT_WS(' ', a.first_name, a.last_name)), ''),
                        es.borrower->>'applicant_id') AS borrower_name
        FROM entity_states es
        LEFT JOIN applicants a ON a.applicant_id = es.borrower->>'applicant_id'
        WHERE es.tenant_id = 'summit'
          AND NOT EXISTS (
              SELECT 1 FROM document_index d
              WHERE d.application_id = es.application_id
                AND d.document_type = 'OFAC_CHECK'
          )
        ORDER BY es.application_id
        """
    )
    return [dict(r) for r in rows]


def _build(row: dict, now: datetime) -> dict:
    ef = {
        "ofac_clear": True,
        "sdn_match": False,
        "pep_match": False,
        "adverse_media": False,
        "checked_at": now.isoformat(),
        "list_date": LIST_DATE,
        "borrower_name": row["borrower_name"],
    }
    return {
        "document_id": f"SEED_OFAC-{row['application_id']}-OFAC_CHECK-0001",
        "application_id": row["application_id"],
        "applicant_id": row["applicant_id"],
        "tenant_id": row["tenant_id"],          # the loan's own tenant ('summit')
        "borrower_role": "primary",
        "extracted_fields": ef,
    }


async def main(commit: bool) -> None:
    c = await asyncpg.connect(_url())
    try:
        before = await c.fetchval(
            "SELECT COUNT(*) FROM document_index WHERE document_type='OFAC_CHECK' "
            "AND application_id IN (SELECT application_id FROM entity_states WHERE tenant_id='summit')"
        )
        roles = [r["borrower_role"] for r in await c.fetch(
            "SELECT DISTINCT borrower_role FROM document_index WHERE borrower_role IS NOT NULL LIMIT 10")]
        targets = await _targets(c)
        now = datetime.now(timezone.utc)
        docs = [_build(t, now) for t in targets]

        print(f"Mode: {'COMMIT' if commit else 'DRY-RUN'}")
        print(f"Existing OFAC_CHECK docs on Summit loans (before): {before}")
        print(f"Summit loans needing an OFAC_CHECK doc: {len(docs)}")
        print(f"(existing borrower_role values in use: {roles})")
        print("\n--- 3 sample rows that would be inserted ---")
        for d in docs[:3]:
            print(json.dumps({**d, "extracted_fields": d["extracted_fields"]}, indent=2, default=str))

        if not docs:
            print("\nNothing to seed.")
            return
        if not commit:
            print(f"\nDRY-RUN: would insert {len(docs)} rows. Re-run with --commit to apply.")
            return

        inserted = 0
        for i in range(0, len(docs), BATCH):
            batch = docs[i:i + BATCH]
            async with c.transaction():
                await c.executemany(
                    """
                    INSERT INTO document_index
                        (document_id, application_id, applicant_id, tenant_id, document_type,
                         document_category, borrower_role, status, confidence_score,
                         extraction_method, s3_key, extracted_fields, received_at, is_current)
                    VALUES ($1,$2,$3,$4,'OFAC_CHECK','identity',$5,'indexed',0.99,'automated',
                            NULL,$6::jsonb,$7,true)
                    ON CONFLICT (document_id) DO NOTHING
                    """,
                    [(d["document_id"], d["application_id"], d["applicant_id"], d["tenant_id"],
                      d["borrower_role"], json.dumps(d["extracted_fields"]), now) for d in batch],
                )
            inserted += len(batch)
            if inserted % 500 == 0 or inserted == len(docs):
                print(f"Seeded {inserted} of {len(docs)}")

        after = await c.fetchval(
            "SELECT COUNT(*) FROM document_index WHERE document_type='OFAC_CHECK' "
            "AND application_id IN (SELECT application_id FROM entity_states WHERE tenant_id='summit')"
        )
        print(f"\nDone. OFAC_CHECK docs on Summit loans: {before} -> {after}")
    finally:
        await c.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true", help="perform the inserts (default: dry-run)")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main(args.commit))

"""Wire OFAC_CHECK documents into entity_states.borrower.identity (Part B).

For every Summit loan that has an OFAC_CHECK document, read sdn_match / pep_match
/ ofac_clear and write them into the borrower JSONB so OFAC screening is sourced
from the document instead of a pre-set default:

    watchlist_match = sdn_match OR pep_match   -> borrower.identity.watchlist_match
    ofac_clear, pep_match, sdn_match           -> borrower.identity.*

Schema note (verified live): entity_states stores the borrower in a `borrower`
JSONB column (there is no entity_type / state_data column). One row per loan.

When a loan has more than one OFAC_CHECK doc, the seeded one (document_id
LIKE 'SEED_OFAC%') wins, else the most recently received.

Usage:
    python scripts/wire_ofac_entity_states.py            # dry-run (default)
    python scripts/wire_ofac_entity_states.py --commit   # apply the updates
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

import asyncpg
from dotenv import load_dotenv


def _url() -> str:
    load_dotenv()
    return os.environ["DATABASE_URL"].replace("+asyncpg", "").replace("postgresql+psycopg2", "postgresql")


def _bool(v) -> bool:
    return v is True or str(v).lower() == "true"


async def _docs(c: asyncpg.Connection) -> list[dict]:
    rows = await c.fetch(
        """
        SELECT DISTINCT ON (application_id)
               application_id, extracted_fields
        FROM document_index
        WHERE document_type = 'OFAC_CHECK'
          AND application_id IN (SELECT application_id FROM entity_states WHERE tenant_id='summit')
        ORDER BY application_id, (document_id LIKE 'SEED_OFAC%') DESC, received_at DESC
        """
    )
    out = []
    for r in rows:
        ef = r["extracted_fields"]
        ef = json.loads(ef) if isinstance(ef, str) else (ef or {})
        sdn, pep, clear = _bool(ef.get("sdn_match")), _bool(ef.get("pep_match")), _bool(ef.get("ofac_clear", True))
        out.append({
            "application_id": r["application_id"],
            "sdn_match": sdn, "pep_match": pep, "ofac_clear": clear,
            "watchlist_match": sdn or pep,
        })
    return out


async def _identity(c: asyncpg.Connection, app_id: str) -> dict:
    b = await c.fetchval(
        "SELECT borrower FROM entity_states WHERE application_id=$1 AND tenant_id='summit'", app_id)
    b = json.loads(b) if isinstance(b, str) else (b or {})
    return b.get("identity", {})


async def main(commit: bool) -> None:
    c = await asyncpg.connect(_url())
    try:
        docs = await _docs(c)
        print(f"Mode: {'COMMIT' if commit else 'DRY-RUN'}")
        print(f"Summit loans with an OFAC_CHECK doc to wire: {len(docs)}")

        print("\n--- before/after for 3 sample loans ---")
        for d in docs[:3]:
            before = await _identity(c, d["application_id"])
            after = {**before, "watchlist_match": d["watchlist_match"], "ofac_clear": d["ofac_clear"],
                     "pep_match": d["pep_match"], "sdn_match": d["sdn_match"]}
            print(f"\n{d['application_id']}")
            print("  before identity:", json.dumps(before, default=str))
            print("  after  identity:", json.dumps(after, default=str))

        if not docs:
            print("\nNothing to wire.")
            return
        if not commit:
            print(f"\nDRY-RUN: would update {len(docs)} entity_states rows. Re-run with --commit to apply.")
            return

        updated = 0
        async with c.transaction():
            for d in docs:
                # Merge onto COALESCE(identity, '{}') so the path is created even
                # when a borrower has no identity object yet (jsonb_set on a nested
                # path is a no-op if the parent key is missing).
                res = await c.execute(
                    """
                    UPDATE entity_states
                    SET borrower = jsonb_set(
                            borrower, '{identity}',
                            COALESCE(borrower->'identity', '{}'::jsonb)
                            || jsonb_build_object(
                                 'watchlist_match', $2::boolean,
                                 'ofac_clear',      $3::boolean,
                                 'pep_match',       $4::boolean,
                                 'sdn_match',       $5::boolean))
                    WHERE application_id=$1 AND tenant_id='summit'
                    """,
                    d["application_id"], d["watchlist_match"], d["ofac_clear"], d["pep_match"], d["sdn_match"],
                )
                if res.endswith(" 1"):
                    updated += 1
        print(f"\nDone. Updated {updated} of {len(docs)} entity_states rows.")
    finally:
        await c.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true", help="apply the updates (default: dry-run)")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main(args.commit))

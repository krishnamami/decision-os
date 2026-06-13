"""Verify the OFAC chain end-to-end across all four layers (Part C).

    document_index.OFAC_CHECK.sdn_match/pep_match
      -> entity_states.borrower.identity.watchlist_match   (jsonb)
      -> vw_fraud_screening_context.watchlist_match        (view, live)
      -> fraud_screening decision boundary_rule "watchlist=..."

Read-only. Defaults to 3 Summit loans; pass an integer to check more.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys

import asyncpg
from dotenv import load_dotenv


def _url() -> str:
    load_dotenv()
    return os.environ["DATABASE_URL"].replace("+asyncpg", "").replace("postgresql+psycopg2", "postgresql")


async def main(limit: int) -> None:
    c = await asyncpg.connect(_url())
    try:
        loans = await c.fetch(
            "SELECT application_id FROM entity_states WHERE tenant_id='summit' ORDER BY application_id LIMIT $1", limit)
        all_ok = True
        for loan in loans:
            app = loan["application_id"]
            print(f"\n=== {app} ===")

            # 1. OFAC_CHECK document (prefer the seeded one)
            doc = await c.fetchrow(
                """SELECT extracted_fields FROM document_index
                   WHERE application_id=$1 AND document_type='OFAC_CHECK'
                   ORDER BY (document_id LIKE 'SEED_OFAC%') DESC, received_at DESC LIMIT 1""", app)
            ef = doc["extracted_fields"] if doc else None
            ef = json.loads(ef) if isinstance(ef, str) else (ef or {})
            print(f"1. OFAC_CHECK doc: {'FOUND' if doc else 'MISSING'} | sdn_match: {ef.get('sdn_match')} | pep_match: {ef.get('pep_match')}")

            # 2. entity_states.borrower.identity
            b = await c.fetchval("SELECT borrower FROM entity_states WHERE application_id=$1 AND tenant_id='summit'", app)
            b = json.loads(b) if isinstance(b, str) else (b or {})
            ident = b.get("identity", {})
            print(f"2. entity_states.identity: watchlist_match={ident.get('watchlist_match')} ofac_clear={ident.get('ofac_clear')} sdn={ident.get('sdn_match')} pep={ident.get('pep_match')}")

            # 3. vw_fraud_screening_context (live view)
            vw = await c.fetchrow("SELECT watchlist_match FROM vw_fraud_screening_context WHERE application_id=$1", app)
            print(f"3. vw_fraud_screening_context.watchlist_match: {vw['watchlist_match'] if vw else 'MISSING'}")

            # 4. fraud_screening decision (current version) — watchlist token in the boundary_rule
            dec = await c.fetchrow(
                """SELECT outcome, boundary_rule FROM decision_outputs
                   WHERE application_id=$1 AND decision_id='fraud_screening' AND superseded_by IS NULL
                   ORDER BY version DESC LIMIT 1""", app)
            wl_tok = None
            if dec and dec["boundary_rule"]:
                m = re.search(r"watchlist=(\w+)", dec["boundary_rule"], re.I)
                wl_tok = m.group(1) if m else None
            print(f"4. fraud_screening: outcome={dec['outcome'] if dec else 'MISSING'} | watchlist token={wl_tok}")

            # consistency: doc -> identity -> view should all agree on the boolean
            doc_wl = bool(ef.get("sdn_match")) or bool(ef.get("pep_match"))
            chain = [doc_wl, ident.get("watchlist_match"), (vw["watchlist_match"] if vw else None)]
            ok = doc is not None and len(set(chain)) == 1
            print(f"   chain consistent (doc OR -> identity -> view = {chain[0]}): {'PASS' if ok else 'FAIL'}")
            all_ok = all_ok and ok
        print(f"\n{'ALL CHECKS PASS' if all_ok else 'SOME CHECKS FAILED'}")
    finally:
        await c.close()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    asyncio.run(main(n))

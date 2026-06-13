"""Onboard a pilot customer from a CSV export (Accord-team tool).

  python scripts/onboard_customer.py --tenant summit --file export.csv [--mapping map.json] [--run-evaluation]

Reads the CSV, applies an optional column mapping, validates, creates entity_states
(+ applications/applicants/assignments), optionally runs AI evaluation, and prints
a summary. Reads DATABASE_URL from .env. NB: writes to the live database.
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    sys.stdout.reconfigure(encoding="utf-8")  # box glyphs on Windows
except Exception:
    pass

from core.onboarding.importer import LoanImporter, evaluate_imported, parse_csv  # noqa: E402


async def main(args) -> None:
    import asyncpg

    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL not set")
    text = Path(args.file).read_text(encoding="utf-8-sig")
    headers, rows = parse_csv(text)
    mapping = json.loads(Path(args.mapping).read_text(encoding="utf-8")) if args.mapping else None

    conn = await asyncpg.connect(url)
    try:
        imp = LoanImporter(args.tenant, None)
        v = imp.validate(rows, mapping)
        if v["errors"]:
            print(f"Validation: {len(v['errors'])} error(s) — these rows will be skipped:")
            for e in v["errors"][:10]:
                print(f"   row {e['row']}: {e['error']}")
        result = await imp.import_rows(conn, rows, mapping)
        ev = {}
        if args.run_evaluation and result["application_ids"]:
            active = await conn.fetchrow("SELECT rules, programs FROM tenant_rules WHERE tenant_id=$1 AND status='active'", args.tenant)
            if active:
                rules = json.loads(active["rules"]) if isinstance(active["rules"], str) else active["rules"]
                programs = json.loads(active["programs"]) if isinstance(active["programs"], str) else (active["programs"] or ["conventional", "fha"])
                ev = await evaluate_imported(conn, args.tenant, result["application_ids"], rules, programs)
        tname = await conn.fetchval("SELECT name FROM tenants WHERE tenant_id=$1", args.tenant) or args.tenant
    finally:
        await conn.close()

    s = result["summary"]
    print("\n=== ONBOARDING COMPLETE ===")
    print(f"  Tenant: {tname}")
    print(f"  Loans imported: {result['imported']}  (skipped {result['skipped']})")
    if ev:
        total = sum(ev.values()) or 1
        print(f"  Loans evaluated: {sum(ev.values())}")
        print("\n  Results:")
        print(f"    {ev.get('allow', 0)} approved ({ev.get('allow', 0) / total * 100:.0f}%)")
        print(f"    {ev.get('block', 0)} blocked ({ev.get('block', 0) / total * 100:.0f}%)")
        print(f"    {ev.get('review', 0)} review ({ev.get('review', 0) / total * 100:.0f}%)")
    print("\n  Assignments:")
    for email, n in sorted(s["assignments"].items(), key=lambda x: -x[1]):
        print(f"    {email}: {n} loans")
    print(f"\n  Avg amount: ${s['avg_amount']:,} · Avg score: {s['avg_score']}")
    print("\n  Ready for pilot: http://accord-alb-588286075.us-east-1.elb.amazonaws.com")
    print(f"  Login: admin@{args.tenant}.com / accord2026\n")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--file", required=True)
    ap.add_argument("--mapping", help="JSON column-mapping file (for non-template CSVs)")
    ap.add_argument("--rules", help="optional tenant rules YAML (overlays already in DB are used)")
    ap.add_argument("--run-evaluation", action="store_true")
    asyncio.run(main(ap.parse_args()))

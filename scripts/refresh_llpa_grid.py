"""Refresh the Fannie Mae LLPA grid via the staging pattern.

The LLPA grid (llpa_adjustments, P0-E) was seeded from the published matrix.
Fannie distributes the matrix as a PDF, not a structured download, so the
refresh is human-in-the-loop:

  1. Download the LLPA Matrix PDF:
       https://singlefamily.fanniemae.com/media/9391/display
  2. Extract the credit-score x LTV table to a CSV with columns:
       agency, adjustment_type, credit_score_min, credit_score_max,
       ltv_min, ltv_max, property_type, loan_purpose, adjustment_pct, description
  3. Stage it:    python scripts/refresh_llpa_grid.py --stage-from-file data/llpa_2026.csv
  4. Approve (governance_admin reviews catalogue_staging)
  5. Promote:     python scripts/refresh_llpa_grid.py --promote --staging-id <id>

Until Fannie publishes a structured feed the download step stays manual;
the staging + promote infrastructure is the durable part.
"""
import argparse
import asyncio
import csv
import io
import json
import os
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

TARGET_TABLE = "llpa_adjustments"

# CSV header -> (column, caster). Optional columns default sensibly.
_COLUMNS = {
    "agency": str,
    "adjustment_type": str,
    "credit_score_min": int,
    "credit_score_max": int,
    "ltv_min": float,
    "ltv_max": float,
    "property_type": str,
    "loan_purpose": str,
    "adjustment_pct": float,
    "description": str,
}


def _db_url() -> str:
    return os.environ["DATABASE_URL"].replace("+asyncpg", "").replace("postgresql+psycopg2", "postgresql")


def _parse_csv(raw_data: str) -> list[dict]:
    rows: list[dict] = []
    reader = csv.DictReader(io.StringIO(raw_data))
    for raw in reader:
        rec: dict = {}
        try:
            for col, cast in _COLUMNS.items():
                val = (raw.get(col) or "").strip()
                if val == "" and col in ("property_type", "loan_purpose", "description"):
                    rec[col] = None
                    continue
                rec[col] = cast(val.replace("%", "")) if cast is not str else val
            rec.setdefault("occupancy_type", raw.get("occupancy_type") or None)
            if rec.get("agency") and rec.get("adjustment_pct") is not None:
                rows.append(rec)
        except (ValueError, KeyError) as e:
            print(f"  Skip row: {e}")
    return rows


async def stage_from_file(conn, path: str, dry_run: bool = False):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        raw_data = f.read()
    rows = _parse_csv(raw_data)
    print(f"Parsed {len(rows)} LLPA rows from {path}")
    if not rows:
        print("No rows parsed — expected headers: " + ", ".join(_COLUMNS))
        return None
    if dry_run:
        print("Dry run — not staging. Sample:")
        for r in rows[:3]:
            print(f"  {r}")
        return rows

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    staging_id = f"fannie_llpa_grid_{ts}"
    await conn.execute(
        """
        INSERT INTO catalogue_staging
            (staging_id, source_name, source_url, target_table, raw_data, status, row_count)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        ON CONFLICT (staging_id) DO NOTHING
        """,
        staging_id,
        "Fannie Mae LLPA Matrix",
        f"file://{os.path.abspath(path)}",
        TARGET_TABLE,
        json.dumps(rows),
        "pending",
        len(rows),
    )
    print(f"Staged: {staging_id}  ({len(rows)} rows, status=pending)")
    print(f"To promote: python scripts/refresh_llpa_grid.py --promote --staging-id {staging_id}")
    return staging_id


async def promote_llpa_from_staging(conn, staging_id: str, reviewed_by: str):
    """Read raw_data JSONB from staging, upsert into llpa_adjustments, mark
    the staging record promoted. Upsert key matches the table's UNIQUE
    constraint (agency, adjustment_type, credit_score_min, ltv_min,
    property_type, loan_purpose)."""
    row = await conn.fetchrow(
        "SELECT raw_data, target_table, status FROM catalogue_staging WHERE staging_id = $1",
        staging_id,
    )
    if not row:
        print(f"Staging ID not found: {staging_id}")
        return
    if row["target_table"] != TARGET_TABLE:
        print(f"Staging record targets {row['target_table']}, not {TARGET_TABLE}")
        return
    if row["status"] == "promoted":
        print("Already promoted")
        return
    if row["status"] == "rejected":
        print("Staging record was rejected — not promoting")
        return

    grid = json.loads(row["raw_data"])
    inserted = updated = 0
    for r in grid:
        was_insert = await conn.fetchval(
            """
            INSERT INTO llpa_adjustments
                (agency, adjustment_type, credit_score_min, credit_score_max,
                 ltv_min, ltv_max, property_type, loan_purpose, occupancy_type,
                 adjustment_pct, description)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
            ON CONFLICT (agency, adjustment_type, credit_score_min, ltv_min,
                         property_type, loan_purpose) DO UPDATE SET
                credit_score_max = EXCLUDED.credit_score_max,
                ltv_max          = EXCLUDED.ltv_max,
                occupancy_type   = EXCLUDED.occupancy_type,
                adjustment_pct   = EXCLUDED.adjustment_pct,
                description      = EXCLUDED.description
            RETURNING (xmax = 0) AS inserted
            """,
            r.get("agency"), r.get("adjustment_type", "credit_score_ltv"),
            r.get("credit_score_min"), r.get("credit_score_max"),
            r.get("ltv_min"), r.get("ltv_max"),
            r.get("property_type"), r.get("loan_purpose"),
            r.get("occupancy_type"), r.get("adjustment_pct"), r.get("description"),
        )
        if was_insert:
            inserted += 1
        else:
            updated += 1

    await conn.execute(
        """
        UPDATE catalogue_staging
        SET status = 'promoted', reviewed_by = $1, reviewed_at = NOW(), promoted_at = NOW()
        WHERE staging_id = $2
        """,
        reviewed_by, staging_id,
    )
    print(f"Promoted {staging_id} -> {TARGET_TABLE}:")
    print(f"  Inserted: {inserted}")
    print(f"  Updated:  {updated}")
    print(f"  Total:    {inserted + updated}")
    print(f"  Reviewed by: {reviewed_by}")


async def list_pending(conn):
    rows = await conn.fetch(
        """
        SELECT staging_id, source_name, row_count, status, download_at
        FROM catalogue_staging WHERE target_table = $1
        ORDER BY download_at DESC LIMIT 20
        """,
        TARGET_TABLE,
    )
    if not rows:
        print("No LLPA staging records found")
        return
    print(f'{"ID":<40} {"Source":<25} {"Rows":>6} {"Status":<10}')
    print("-" * 90)
    for r in rows:
        print(f'{r["staging_id"]:<40} {r["source_name"]:<25} {r["row_count"] or 0:>6} {r["status"]:<10}')


async def main():
    parser = argparse.ArgumentParser(description="Refresh Fannie LLPA grid (staging pattern)")
    parser.add_argument("--stage-from-file", type=str, help="CSV extracted from the LLPA Matrix PDF")
    parser.add_argument("--promote", action="store_true")
    parser.add_argument("--staging-id", type=str)
    parser.add_argument("--reviewed-by", type=str, default="governance_admin")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    import asyncpg
    conn = await asyncpg.connect(_db_url())
    try:
        if args.list:
            await list_pending(conn)
        elif args.stage_from_file:
            await stage_from_file(conn, args.stage_from_file, args.dry_run)
        elif args.promote:
            if not args.staging_id:
                print("--staging-id required")
                return
            await promote_llpa_from_staging(conn, args.staging_id, args.reviewed_by)
        else:
            parser.print_help()
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())

"""Refresh FHFA county conforming loan limits via the staging pattern.

Flow:
  download  -> parse FHFA CSV -> stage in catalogue_staging (pending)
  approve   -> governance_admin reviews
  promote   -> upsert into county_loan_limits, mark staging promoted

Source: FHFA Conforming Loan Limits (annual, published ~November).
  https://www.fhfa.gov/.../Conforming-Loan-Limits/FullCountyLoanLimitList{year}.csv

Usage:
  python scripts/refresh_county_limits.py --year 2026 --download [--dry-run]
  python scripts/refresh_county_limits.py --year 2026 --from-file data/fhfa_2026.csv
  python scripts/refresh_county_limits.py --promote --staging-id <id> [--reviewed-by NAME]
  python scripts/refresh_county_limits.py --list
"""
import argparse
import asyncio
import csv
import io
import json
import os
import urllib.request
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

# 2025 baseline conforming limit — one-unit above this is a high-cost area.
HIGH_COST_THRESHOLD = 806500

# FHFA has shuffled this filename over the years; try the known patterns.
FHFA_URL_PATTERNS = [
    "https://www.fhfa.gov/DataTools/Downloads/Documents/Conforming-Loan-Limits/FullCountyLoanLimitList{year}_Table.csv",
    "https://www.fhfa.gov/DataTools/Downloads/Documents/Conforming-Loan-Limits/FullCountyLoanLimitList{year}.csv",
]


def _db_url() -> str:
    return os.environ["DATABASE_URL"].replace("+asyncpg", "").replace("postgresql+psycopg2", "postgresql")


def _parse_csv(raw_data: str, year: int) -> list[dict]:
    """Parse FHFA CSV text into county dicts. Column names vary by year, so
    each field tries a list of known header spellings."""
    counties: list[dict] = []
    reader = csv.DictReader(io.StringIO(raw_data))

    def pick(row, keys, default=""):
        for k in keys:
            if k in row and row[k] is not None and str(row[k]).strip():
                return str(row[k]).strip()
        return default

    def parse_limit(row, keys):
        for k in keys:
            v = (row.get(k) or "").replace(",", "").replace("$", "").strip()
            if v and v.upper() != "NA":
                try:
                    return float(v)
                except ValueError:
                    pass
        return None

    for row in reader:
        try:
            state = pick(row, ["State", "STATE", "State Code"]).upper()
            county = pick(row, ["County Name", "COUNTY NAME", "County"])
            fips = pick(row, ["FIPS Code", "FIPS", "fips"]).zfill(5)
            one = parse_limit(row, ["One-Unit Limit", "1 Unit", "Limit1", "ONE_UNIT"])
            two = parse_limit(row, ["Two-Unit Limit", "2 Units", "Limit2", "TWO_UNIT"])
            three = parse_limit(row, ["Three-Unit Limit", "3 Units", "Limit3", "THREE_UNIT"])
            four = parse_limit(row, ["Four-Unit Limit", "4 Units", "Limit4", "FOUR_UNIT"])
            if not state or not county or not one:
                continue
            counties.append({
                "state_code": state[:2],
                "county_name": county,
                "fips_code": fips,
                "one_unit_limit": one,
                "two_unit_limit": two,
                "three_unit_limit": three,
                "four_unit_limit": four,
                "high_cost_area": (one > HIGH_COST_THRESHOLD) if one else False,
                "effective_year": year,
            })
        except Exception as e:  # noqa: BLE001
            print(f"  Skip row: {e}")
            continue
    return counties


async def _stage(conn, year, counties, source_url):
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    staging_id = f"fhfa_county_limits_{year}_{ts}"
    await conn.execute(
        """
        INSERT INTO catalogue_staging
            (staging_id, source_name, source_url, target_table, raw_data, status, row_count)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        ON CONFLICT (staging_id) DO NOTHING
        """,
        staging_id,
        f"FHFA County Conforming Limits {year}",
        source_url,
        "county_loan_limits",
        json.dumps(counties),
        "pending",
        len(counties),
    )
    print(f"Staged: {staging_id}")
    print(f"Rows:   {len(counties)}")
    print("Status: pending (awaiting approval)")
    print("\nTo approve and promote:")
    print(f"  python scripts/refresh_county_limits.py --promote --staging-id {staging_id}")
    return staging_id


async def download_and_stage(conn, year, dry_run=False, from_file=None):
    raw_data, source_url = None, None
    if from_file:
        with open(from_file, "r", encoding="utf-8", errors="replace") as f:
            raw_data = f.read()
        source_url = f"file://{os.path.abspath(from_file)}"
        print(f"Loaded {len(raw_data)} bytes from {from_file}")
    else:
        for pattern in FHFA_URL_PATTERNS:
            url = pattern.format(year=year)
            try:
                print(f"Trying: {url}")
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=30) as response:
                    raw_data = response.read().decode("utf-8", errors="replace")
                    source_url = url
                    print(f"Downloaded {len(raw_data)} bytes")
                    break
            except Exception as e:  # noqa: BLE001
                print(f"  Failed: {e}")

    if not raw_data:
        print("\nCould not download from FHFA. Manual process:")
        print("  1. https://www.fhfa.gov/DataTools/Downloads/Pages/Conforming-Loan-Limits.aspx")
        print(f"  2. Download the {year} full county list as CSV")
        print(f"  3. Save as data/fhfa_{year}.csv")
        print(f"  4. python scripts/refresh_county_limits.py --year {year} --from-file data/fhfa_{year}.csv")
        return None

    counties = _parse_csv(raw_data, year)
    print(f"Parsed {len(counties)} counties")
    if not counties:
        print("No counties parsed — check CSV format. First 3 lines:")
        for line in raw_data.split("\n")[:3]:
            print(f"  {line}")
        return None

    if dry_run:
        print("Dry run — not staging. Sample rows:")
        for c in counties[:3]:
            print(f"  {c}")
        return counties

    return await _stage(conn, year, counties, source_url)


async def _ensure_county_table(conn):
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS county_loan_limits (
            id                UUID DEFAULT gen_random_uuid() PRIMARY KEY,
            state_code        CHAR(2) NOT NULL,
            county_name       VARCHAR(100) NOT NULL,
            fips_code         VARCHAR(5),
            one_unit_limit    NUMERIC NOT NULL,
            two_unit_limit    NUMERIC,
            three_unit_limit  NUMERIC,
            four_unit_limit   NUMERIC,
            high_cost_area    BOOLEAN DEFAULT FALSE,
            effective_year    INTEGER NOT NULL,
            source_staging_id VARCHAR(100),
            promoted_at       TIMESTAMPTZ,
            created_at        TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE (state_code, county_name, effective_year)
        )
        """
    )


async def promote_to_county_limits(conn, staging_id, reviewed_by):
    row = await conn.fetchrow(
        "SELECT raw_data, status FROM catalogue_staging WHERE staging_id = $1", staging_id
    )
    if not row:
        print(f"Staging ID not found: {staging_id}")
        return
    if row["status"] == "promoted":
        print("Already promoted")
        return
    if row["status"] == "rejected":
        print("Staging record was rejected — not promoting")
        return

    counties = json.loads(row["raw_data"])
    await _ensure_county_table(conn)

    inserted = updated = 0
    for c in counties:
        # xmax = 0 on the returned row means it was a fresh INSERT, not an
        # ON CONFLICT UPDATE (asyncpg's status tag can't distinguish them).
        was_insert = await conn.fetchval(
            """
            INSERT INTO county_loan_limits
                (state_code, county_name, fips_code, one_unit_limit, two_unit_limit,
                 three_unit_limit, four_unit_limit, high_cost_area, effective_year,
                 source_staging_id, promoted_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10, NOW())
            ON CONFLICT (state_code, county_name, effective_year) DO UPDATE SET
                one_unit_limit    = EXCLUDED.one_unit_limit,
                two_unit_limit    = EXCLUDED.two_unit_limit,
                three_unit_limit  = EXCLUDED.three_unit_limit,
                four_unit_limit   = EXCLUDED.four_unit_limit,
                high_cost_area    = EXCLUDED.high_cost_area,
                source_staging_id = EXCLUDED.source_staging_id,
                promoted_at       = NOW()
            RETURNING (xmax = 0) AS inserted
            """,
            c["state_code"], c["county_name"], c.get("fips_code"),
            c["one_unit_limit"], c.get("two_unit_limit"), c.get("three_unit_limit"),
            c.get("four_unit_limit"), c.get("high_cost_area", False),
            c["effective_year"], staging_id,
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
    print(f"Promoted {staging_id}:")
    print(f"  Inserted: {inserted}")
    print(f"  Updated:  {updated}")
    print(f"  Total:    {inserted + updated}")
    print(f"  Reviewed by: {reviewed_by}")


async def list_pending(conn):
    rows = await conn.fetch(
        """
        SELECT staging_id, source_name, row_count, status, download_at
        FROM catalogue_staging ORDER BY download_at DESC LIMIT 20
        """
    )
    if not rows:
        print("No staging records found")
        return
    print(f'{"ID":<45} {"Source":<35} {"Rows":>6} {"Status":<10}')
    print("-" * 100)
    for r in rows:
        print(f'{r["staging_id"]:<45} {r["source_name"]:<35} {r["row_count"] or 0:>6} {r["status"]:<10}')


async def main():
    parser = argparse.ArgumentParser(description="Refresh FHFA county limits")
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--from-file", type=str)
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
        elif args.download or args.from_file:
            await download_and_stage(conn, args.year, args.dry_run, args.from_file)
        elif args.promote:
            if not args.staging_id:
                print("--staging-id required")
                return
            await promote_to_county_limits(conn, args.staging_id, args.reviewed_by)
        else:
            parser.print_help()
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())

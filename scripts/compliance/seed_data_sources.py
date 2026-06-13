"""Seed data-freshness rows + a couple of rule-change alerts.

  python scripts/compliance/seed_data_sources.py

Idempotent: upserts data_source_status by source_id; refreshes the alert set.
"""

import asyncio
import os
from datetime import date

from dotenv import load_dotenv

load_dotenv()

# (source_id, name, url, last_sql, next_sql, count) — last/next are SQL expressions.
SOURCES = [
    ("ofac_sdn", "OFAC SDN List", "https://www.treasury.gov/ofac/downloads/sdn.xml",
     "NOW() - interval '6 hours'", "NOW() + interval '18 hours'", 12847),
    ("conforming_limits", "FHFA Conforming Loan Limits", "https://www.fhfa.gov/DataTools/Downloads",
     "TIMESTAMP '2026-01-15'", "TIMESTAMP '2027-01-15'", 3233),
    ("fha_limits", "HUD FHA Loan Limits", "https://entp.hud.gov/idapp/html/hicostlook.cfm",
     "TIMESTAMP '2026-01-15'", "TIMESTAMP '2027-01-15'", 3233),
    ("fannie_selling_guide", "Fannie Mae Selling Guide", "https://selling-guide.fanniemae.com",
     "TIMESTAMP '2026-06-10'", "TIMESTAMP '2026-07-01'", 96),
    ("freddie_guide", "Freddie Mac Seller/Servicer Guide", "https://guide.freddiemac.com",
     "TIMESTAMP '2026-06-08'", "TIMESTAMP '2026-07-01'", 82),
    ("fha_handbook", "FHA Handbook 4000.1", "https://www.hud.gov/program_offices/housing/sfh",
     "TIMESTAMP '2026-06-01'", "TIMESTAMP '2026-09-01'", 45),
    ("va_handbook", "VA Lender's Handbook", "https://www.benefits.va.gov/WARMS/pam26_7.asp",
     "TIMESTAMP '2026-06-01'", "TIMESTAMP '2026-09-01'", 28),
    ("fred_rates", "Federal Reserve Interest Rates (FRED)", "https://fred.stlouisfed.org",
     "NOW() - interval '2 days'", "NOW() + interval '5 days'", 1),
]

# (source, title, description, url, published_date)
ALERTS = [
    ("fannie_sel", "Selling Guide Announcement SEL-2026-05",
     "Updates to self-employed income documentation and reserve requirements for second homes.",
     "https://selling-guide.fanniemae.com", "2026-06-09"),
    ("hud_ml", "FHA Mortgagee Letter 2026-09",
     "Revised manual underwriting compensating-factor matrix for DTI ratios above 43%.",
     "https://www.hud.gov", "2026-06-05"),
]


async def main() -> None:
    import asyncpg

    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL not set")
    conn = await asyncpg.connect(url)
    try:
        for sid, name, src_url, last_sql, next_sql, count in SOURCES:
            await conn.execute(
                f"INSERT INTO data_source_status "
                f"(source_id, source_name, source_url, last_download, last_success, record_count, status, next_scheduled, updated_at) "
                f"VALUES ($1,$2,$3,{last_sql},{last_sql},$4,'ok',{next_sql},NOW()) "
                f"ON CONFLICT (source_id) DO UPDATE SET "
                f"source_name=EXCLUDED.source_name, source_url=EXCLUDED.source_url, "
                f"last_download=EXCLUDED.last_download, last_success=EXCLUDED.last_success, "
                f"record_count=EXCLUDED.record_count, status='ok', next_scheduled=EXCLUDED.next_scheduled, updated_at=NOW()",
                sid, name, src_url, count,
            )
        async with conn.transaction():
            await conn.execute("DELETE FROM rule_change_alerts WHERE status='new'")
            for source, title, desc, a_url, pub in ALERTS:
                await conn.execute(
                    "INSERT INTO rule_change_alerts (source, title, description, url, published_date, status) "
                    "VALUES ($1,$2,$3,$4,$5,'new')",
                    source, title, desc, a_url, date.fromisoformat(pub),
                )
        ns = await conn.fetchval("SELECT count(*) FROM data_source_status")
        na = await conn.fetchval("SELECT count(*) FROM rule_change_alerts WHERE status='new'")
        print(f"Seeded data_source_status: {ns} sources · rule_change_alerts: {na} new")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())

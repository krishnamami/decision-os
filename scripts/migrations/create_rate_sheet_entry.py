"""Create rate_sheet_entry (lender rate-sheet rows). Idempotent.

NOTE: the existing `rate_schedule_period` table is an ARM rate-adjustment
structure (period_sequence, periodic_cap, …) — incompatible with rate-sheet
rows, so PROMPT E uses this dedicated table instead.
"""
import asyncio
import os

from dotenv import load_dotenv

load_dotenv()


async def main() -> None:
    import asyncpg
    url = os.environ["DATABASE_URL"].replace("+asyncpg", "").replace("postgresql+psycopg2", "postgresql")
    conn = await asyncpg.connect(url)
    try:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS rate_sheet_entry (
                rate_sheet_entry_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id        varchar NOT NULL,
                product_id       varchar NOT NULL,
                credit_band      varchar NOT NULL,
                ltv_max          numeric NOT NULL,
                base_rate        numeric NOT NULL,
                llpa_adjustment  numeric NOT NULL DEFAULT 0,
                effective_date   date NOT NULL,
                uploaded_by      uuid,
                uploaded_at      timestamptz NOT NULL DEFAULT now(),
                UNIQUE (tenant_id, product_id, credit_band, ltv_max, effective_date)
            )
            """
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_rate_sheet_entry_tenant ON rate_sheet_entry(tenant_id, effective_date DESC)"
        )
        print("rate_sheet_entry ensured")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())

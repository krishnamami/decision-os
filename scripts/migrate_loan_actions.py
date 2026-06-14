"""Create the loan_actions table (workbench redesign) — documented human actions
with reasons, for the decision-notes thread, similar-cases matching, and the
examiner-readiness score. Idempotent."""
import asyncio
import os
import sys

import asyncpg
from dotenv import load_dotenv

DDL = """
CREATE TABLE IF NOT EXISTS loan_actions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    application_id VARCHAR NOT NULL,
    tenant_id VARCHAR NOT NULL,
    action_type VARCHAR NOT NULL,
    reason_category VARCHAR,
    reason_text TEXT NOT NULL,
    performed_by VARCHAR NOT NULL,
    performed_at TIMESTAMPTZ DEFAULT NOW(),
    related_decision_id VARCHAR,
    visible_to TEXT[],
    metadata JSONB DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_loan_actions_application ON loan_actions(application_id, tenant_id);
CREATE INDEX IF NOT EXISTS idx_loan_actions_performed_at ON loan_actions(performed_at DESC);
"""


async def main() -> None:
    load_dotenv()
    url = os.environ["DATABASE_URL"].replace("+asyncpg", "").replace("postgresql+psycopg2", "postgresql")
    c = await asyncpg.connect(url)
    try:
        await c.execute(DDL)
        reg = await c.fetchval("SELECT to_regclass('public.loan_actions')")
        cols = [r["column_name"] for r in await c.fetch(
            "SELECT column_name FROM information_schema.columns WHERE table_name='loan_actions' ORDER BY ordinal_position")]
        idx = [r["indexname"] for r in await c.fetch(
            "SELECT indexname FROM pg_indexes WHERE tablename='loan_actions'")]
        print("table:", reg)
        print("columns:", cols)
        print("indexes:", idx)
    finally:
        await c.close()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())

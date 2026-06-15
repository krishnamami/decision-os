"""Create agent_learnings + policy_proposals tables (PROMPT L).

  python scripts/migrations/create_agent_learnings.py

Idempotent — safe to re-run (CREATE TABLE/INDEX IF NOT EXISTS).
"""
import asyncio
import os

from dotenv import load_dotenv

load_dotenv()

SQL = """
CREATE TABLE IF NOT EXISTS agent_learnings (
    agent_learning_id    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id            text NOT NULL,
    agent_id             text NOT NULL,
    persona              text NOT NULL,
    decision_id          text NOT NULL,
    trace_id             uuid,
    application_id       text,
    original_ai_decision text NOT NULL,
    human_decision       text NOT NULL,
    override_reason      text NOT NULL,
    override_reason_code text,
    reviewer_role        text NOT NULL,
    reviewer_id          text,
    lesson               text NOT NULL,
    similarity_tags      text[] DEFAULT '{}',
    captured_at          timestamptz DEFAULT NOW(),
    expires_at           timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_agent_learnings_agent
    ON agent_learnings (agent_id, decision_id, tenant_id);
CREATE INDEX IF NOT EXISTS idx_agent_learnings_tags
    ON agent_learnings USING GIN (similarity_tags);

CREATE TABLE IF NOT EXISTS policy_proposals (
    proposal_id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         text NOT NULL,
    decision_id       text NOT NULL,
    boundary_rule     text NOT NULL,
    override_count    int NOT NULL,
    pattern_summary   text NOT NULL,
    proposed_change   text NOT NULL,
    proposed_rules_json jsonb,
    status            text DEFAULT 'pending',
    reviewed_by       text,
    reviewed_at       timestamptz,
    created_at        timestamptz DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_policy_proposals_tenant
    ON policy_proposals (tenant_id, status);
"""


async def main():
    import asyncpg
    conn = await asyncpg.connect(
        os.environ['DATABASE_URL']
        .replace('+asyncpg', '')
        .replace('postgresql+psycopg2', 'postgresql')
    )
    await conn.execute(SQL)
    print('Tables created: agent_learnings, policy_proposals')
    await conn.close()


asyncio.run(main())

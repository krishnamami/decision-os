-- ============================================================
-- MiroFish — persistence for the multi-agent simulation engine
-- ============================================================
-- Idempotent: safe to run repeatedly (IF NOT EXISTS throughout).
-- Apply with:  python scripts/mirofish.py migrate
--          or  psql "$DATABASE_URL" -f scripts/migrations/create_mirofish_tables.sql
-- ============================================================

-- ── Debate transcripts ──────────────────────────────────────
CREATE TABLE IF NOT EXISTS mirofish_debates (
    debate_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    application_id     VARCHAR NOT NULL,
    tenant_id          VARCHAR NOT NULL DEFAULT 'default',
    question           TEXT NOT NULL,
    rounds             JSONB NOT NULL,
    final_consensus    VARCHAR,
    consensus_count    JSONB,
    recommendation     TEXT,
    emergent_insights  JSONB,
    duration_seconds   FLOAT,
    created_at         TIMESTAMP DEFAULT NOW()
);

-- ── Policy / stress / regulatory simulation runs ────────────
CREATE TABLE IF NOT EXISTS mirofish_simulations (
    simulation_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id          VARCHAR NOT NULL DEFAULT 'default',
    scenario_name      VARCHAR NOT NULL,
    scenario_type      VARCHAR NOT NULL,
    scenario_config    JSONB NOT NULL,
    status             VARCHAR DEFAULT 'pending',
    total_apps         INT,
    affected_apps      INT,
    flipped            JSONB,
    impact             JSONB,
    agent_insights     JSONB,
    started_at         TIMESTAMP,
    completed_at       TIMESTAMP,
    created_at         TIMESTAMP DEFAULT NOW()
);

-- ── Portfolio swarm scans ───────────────────────────────────
CREATE TABLE IF NOT EXISTS mirofish_swarm_runs (
    swarm_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id          VARCHAR NOT NULL DEFAULT 'default',
    total_apps_scanned INT,
    insights           JSONB,
    agent_summaries    JSONB,
    created_at         TIMESTAMP DEFAULT NOW()
);

-- ── Activity log — an append-only feed of what happened in the
--    workbench / engines (debate run, decision reverted, condition
--    cleared, simulation run, …). One row per event.
CREATE TABLE IF NOT EXISTS activity_log (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id          VARCHAR NOT NULL DEFAULT 'default',
    application_id     VARCHAR,
    actor              VARCHAR,          -- agent id / reviewer name / 'system'
    action             VARCHAR NOT NULL, -- e.g. 'debate_run','decision_reverted'
    target             VARCHAR,          -- object the action touched (decision_id, debate_id, …)
    detail             JSONB DEFAULT '{}'::jsonb,
    created_at         TIMESTAMP DEFAULT NOW()
);

-- ── Conditions — underwriting / closing conditions tracked per
--    application until cleared or waived.
CREATE TABLE IF NOT EXISTS conditions (
    condition_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id          VARCHAR NOT NULL DEFAULT 'default',
    application_id     VARCHAR NOT NULL,
    decision_id        VARCHAR,
    category           VARCHAR,                          -- income / credit / title / insurance / compliance
    description        TEXT NOT NULL,
    status             VARCHAR NOT NULL DEFAULT 'open',  -- open | cleared | waived
    severity           VARCHAR DEFAULT 'standard',       -- prior_to_close | standard | informational
    created_by         VARCHAR,
    created_at         TIMESTAMP DEFAULT NOW(),
    cleared_by         VARCHAR,
    cleared_at         TIMESTAMP
);

-- ── decision_outputs versioning + stale flag (idempotent) ───
ALTER TABLE decision_outputs ADD COLUMN IF NOT EXISTS version INT DEFAULT 1;
ALTER TABLE decision_outputs ADD COLUMN IF NOT EXISTS stale BOOLEAN DEFAULT false;

-- ── Indexes ─────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_debates_app        ON mirofish_debates(application_id);
CREATE INDEX IF NOT EXISTS idx_debates_tenant     ON mirofish_debates(tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_simulations_tenant ON mirofish_simulations(tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_swarm_tenant       ON mirofish_swarm_runs(tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_activity_app       ON activity_log(application_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_activity_tenant    ON activity_log(tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_conditions_app     ON conditions(application_id, status);
CREATE INDEX IF NOT EXISTS idx_conditions_tenant  ON conditions(tenant_id, status);

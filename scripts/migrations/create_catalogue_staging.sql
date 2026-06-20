-- ============================================================
-- catalogue_staging
-- ------------------------------------------------------------
-- Landing zone for all external catalogue data (FHFA county
-- limits, Fannie LLPA, agency_guidelines, regulatory_rules).
-- Flow: download -> stage (status='pending') -> governance_admin
-- approves/rejects -> promote to the operational target_table
-- (status='promoted'). Nothing reaches an operational table
-- without passing through here.
-- ============================================================

CREATE TABLE IF NOT EXISTS catalogue_staging (
    id            UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    staging_id    VARCHAR(100) NOT NULL,
    source_name   VARCHAR(100) NOT NULL,
    source_url    TEXT NOT NULL,
    target_table  VARCHAR(100) NOT NULL,
    raw_data      JSONB NOT NULL,
    status        VARCHAR(20) DEFAULT 'pending'
                  CHECK (status IN ('pending', 'approved', 'rejected', 'promoted')),
    row_count     INTEGER,
    download_at   TIMESTAMPTZ DEFAULT NOW(),
    reviewed_by   VARCHAR(100),
    reviewed_at   TIMESTAMPTZ,
    promoted_at   TIMESTAMPTZ,
    notes         TEXT,
    UNIQUE (staging_id)
);

CREATE INDEX IF NOT EXISTS idx_catalogue_staging_status
    ON catalogue_staging (status, target_table);

-- Governance: anyone may read / stage; only governance_admin (or the
-- platform edms_admin) may approve/promote (UPDATE).
ALTER TABLE catalogue_staging ENABLE ROW LEVEL SECURITY;

-- CREATE POLICY is not idempotent, so drop-then-create to keep this
-- migration re-runnable.
DROP POLICY IF EXISTS catalogue_staging_read    ON catalogue_staging;
DROP POLICY IF EXISTS catalogue_staging_insert  ON catalogue_staging;
DROP POLICY IF EXISTS catalogue_staging_approve ON catalogue_staging;

CREATE POLICY catalogue_staging_read
    ON catalogue_staging FOR SELECT
    USING (true);

CREATE POLICY catalogue_staging_insert
    ON catalogue_staging FOR INSERT
    WITH CHECK (true);

CREATE POLICY catalogue_staging_approve
    ON catalogue_staging FOR UPDATE
    USING (current_user = 'governance_admin' OR current_user = 'edms_admin');

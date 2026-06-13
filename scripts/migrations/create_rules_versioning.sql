-- Accord Rules Dashboard — advanced versioning (rollback, scheduling, shadow,
-- emergency, examination freeze, retrospective, reconstruction, pinning,
-- expiration). Additive + idempotent — safe to re-run.

-- ── Extend tenant_rules for advanced versioning ─────────────────────
ALTER TABLE tenant_rules ADD COLUMN IF NOT EXISTS change_type VARCHAR DEFAULT 'standard';
  -- standard, rollback, emergency, scheduled, shadow
ALTER TABLE tenant_rules ADD COLUMN IF NOT EXISTS scheduled_for TIMESTAMP;
ALTER TABLE tenant_rules ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP;
ALTER TABLE tenant_rules ADD COLUMN IF NOT EXISTS rolled_back_from INT;
ALTER TABLE tenant_rules ADD COLUMN IF NOT EXISTS pipeline_policy VARCHAR DEFAULT 'grandfather';
  -- grandfather, immediate, cutoff_date
ALTER TABLE tenant_rules ADD COLUMN IF NOT EXISTS pipeline_cutoff_date DATE;
ALTER TABLE tenant_rules ADD COLUMN IF NOT EXISTS ratified_by UUID;
ALTER TABLE tenant_rules ADD COLUMN IF NOT EXISTS ratified_at TIMESTAMP;
ALTER TABLE tenant_rules ADD COLUMN IF NOT EXISTS channel VARCHAR DEFAULT 'all';
  -- all, retail, wholesale, correspondent
ALTER TABLE tenant_rules ADD COLUMN IF NOT EXISTS shadow_duration_days INT;
ALTER TABLE tenant_rules ADD COLUMN IF NOT EXISTS emergency_type VARCHAR;

-- ── Shadow-mode dual evaluations ────────────────────────────────────
CREATE TABLE IF NOT EXISTS shadow_evaluations (
  eval_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  application_id VARCHAR NOT NULL,
  tenant_id VARCHAR NOT NULL,
  active_version INT NOT NULL,
  shadow_version INT NOT NULL,
  active_result VARCHAR,      -- allow, block, review, escalate
  shadow_result VARCHAR,
  active_details JSONB,
  shadow_details JSONB,
  difference TEXT,
  created_at TIMESTAMP DEFAULT NOW()
);

-- ── Rule pinning on loans ───────────────────────────────────────────
ALTER TABLE entity_states ADD COLUMN IF NOT EXISTS pinned_rule_version UUID;
ALTER TABLE entity_states ADD COLUMN IF NOT EXISTS pinned_at TIMESTAMP;
ALTER TABLE entity_states ADD COLUMN IF NOT EXISTS application_date DATE;

-- ── Examination freeze periods ──────────────────────────────────────
CREATE TABLE IF NOT EXISTS examination_periods (
  exam_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id VARCHAR NOT NULL,
  examiner VARCHAR,
  reason TEXT,
  started_at TIMESTAMP DEFAULT NOW(),
  started_by UUID REFERENCES users(user_id),
  ended_at TIMESTAMP,
  ended_by UUID,
  is_active BOOLEAN DEFAULT true
);

-- ── Rescreen events (OFAC updates, emergency re-evaluations) ────────
CREATE TABLE IF NOT EXISTS rescreen_events (
  rescreen_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id VARCHAR NOT NULL,
  reason VARCHAR NOT NULL,
  source VARCHAR,
  triggered_at TIMESTAMP DEFAULT NOW(),
  triggered_by UUID,
  loans_rescreened INT DEFAULT 0,
  new_flags INT DEFAULT 0,
  completed_at TIMESTAMP
);

-- ── Retrospective analysis runs ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS retrospective_analyses (
  analysis_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id VARCHAR NOT NULL,
  date_range_start DATE,
  date_range_end DATE,
  original_version INT,
  simulated_version INT,
  total_loans INT,
  original_approved INT,
  original_denied INT,
  simulated_approved INT,
  simulated_denied INT,
  delta_details JSONB,
  run_by UUID REFERENCES users(user_id),
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_shadow_tenant ON shadow_evaluations(tenant_id, shadow_version);
CREATE INDEX IF NOT EXISTS idx_exam_active ON examination_periods(tenant_id, is_active);
CREATE INDEX IF NOT EXISTS idx_tenant_rules_sched ON tenant_rules(status, scheduled_for);

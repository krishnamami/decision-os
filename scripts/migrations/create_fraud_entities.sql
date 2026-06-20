-- scripts/migrations/create_fraud_entities.sql
-- FR-A — fraud signal entity model. Schema only (same pattern as TL-A / CR-A /
-- AV-A). The current fraud pipeline carries a single score derived from
-- identity-doc presence; this table adds specific fraud signals (income/
-- employment mismatch, occupancy risk, undisclosed debt, etc.), populated by
-- the FR-B..FR-D resolvers.

-- ─────────────────────────────────────────────
-- FRAUD_SIGNALS
-- One row per fraud signal detected.
-- Populated by FR-B through FR-D resolvers.
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS fraud_signals (
    id               UUID DEFAULT gen_random_uuid()
                     PRIMARY KEY,
    application_id   VARCHAR(50) NOT NULL,
    tenant_id        VARCHAR(50) NOT NULL,

    -- Signal classification
    signal_type      VARCHAR(50) NOT NULL
                     CHECK (signal_type IN (
                         'income_inflation',
                         'income_mismatch',
                         'employment_mismatch',
                         'employer_inconsistency',
                         'address_mismatch',
                         'occupancy_risk',
                         'straw_buyer',
                         'undisclosed_debt',
                         'rapid_credit_inquiry',
                         'synthetic_identity',
                         'document_alteration',
                         'large_deposit_pattern',
                         'value_inflation',
                         'flip_transaction',
                         'other'
                     )),

    severity         VARCHAR(20) NOT NULL
                     CHECK (severity IN (
                         'informational',
                         'low',
                         'medium',
                         'high',
                         'critical'
                     )),

    -- Signal details
    description      TEXT NOT NULL,
    detected_value   TEXT,
    expected_value   TEXT,
    variance_pct     NUMERIC,
    source_docs      TEXT[],

    -- Action
    auto_block       BOOLEAN DEFAULT FALSE,
    requires_review  BOOLEAN DEFAULT TRUE,
    condition_code   VARCHAR(100),

    -- Resolution
    resolved         BOOLEAN DEFAULT FALSE,
    resolution_notes TEXT,
    resolved_by      VARCHAR(100),
    resolved_at      TIMESTAMPTZ,

    created_at       TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS
    idx_fraud_signals_app
    ON fraud_signals(application_id, tenant_id);

CREATE INDEX IF NOT EXISTS
    idx_fraud_signals_severity
    ON fraud_signals(application_id, severity)
    WHERE severity IN ('high','critical');

CREATE INDEX IF NOT EXISTS
    idx_fraud_signals_auto_block
    ON fraud_signals(application_id, auto_block)
    WHERE auto_block = TRUE;


-- RLS
ALTER TABLE fraud_signals
    ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
  DROP POLICY IF EXISTS fs_read ON fraud_signals;
  CREATE POLICY fs_read ON fraud_signals
      FOR SELECT USING (
          tenant_id = current_setting(
              'app.tenant_id', true
          ) OR current_user = 'edms_admin'
      );
  DROP POLICY IF EXISTS fs_write ON fraud_signals;
  CREATE POLICY fs_write ON fraud_signals
      FOR INSERT WITH CHECK (true);
  DROP POLICY IF EXISTS fs_update ON fraud_signals;
  CREATE POLICY fs_update ON fraud_signals
      FOR UPDATE USING (
          current_user = 'edms_admin'
          OR current_user = 'governance_admin'
      );
END $$;

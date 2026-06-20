-- scripts/migrations/create_decision_trace.sql  (TR-A)
-- Complete, immutable decision trace — what a regulator / repurchase defense /
-- UW reads to reconstruct a decision from the record alone.

-- ─────────────────────────────────────────────
-- DECISION_TRACE
-- One row per decision. Append-only; reruns add a new row and link via
-- superseded_by.
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS decision_trace (
    id               UUID DEFAULT gen_random_uuid()
                     PRIMARY KEY,
    application_id   VARCHAR(50) NOT NULL,
    tenant_id        VARCHAR(50) NOT NULL,
    decision_id      UUID,

    trace_version    INTEGER DEFAULT 1,

    -- What we knew when we decided
    input_snapshot   JSONB NOT NULL DEFAULT '{}',
    -- What each persona concluded
    persona_traces   JSONB NOT NULL DEFAULT '{}',
    -- Which rules were evaluated (TR-B)
    policy_trace     JSONB NOT NULL DEFAULT '{}',
    -- Which docs proved which facts
    evidence_trace   JSONB NOT NULL DEFAULT '{}',

    -- VARCHAR(30): 'approve_with_conditions' is 23 chars (spec said 20).
    final_outcome    VARCHAR(30) NOT NULL
                     CHECK (final_outcome IN (
                         'approve',
                         'approve_with_conditions',
                         'escalate',
                         'block',
                         'refer',
                         'incomplete'
                     )),
    outcome_reason   TEXT,
    confidence_score NUMERIC,

    conditions_snapshot JSONB DEFAULT '[]',

    -- Loan data snapshot
    loan_amount      NUMERIC,
    ltv              NUMERIC,
    dti              NUMERIC,
    credit_score     INTEGER,
    loan_type        VARCHAR(50),
    property_type    VARCHAR(50),

    -- Audit
    decided_at       TIMESTAMPTZ DEFAULT NOW(),
    decided_by       VARCHAR(100)
                     DEFAULT 'accord_engine',
    reviewed_by      VARCHAR(100),
    reviewed_at      TIMESTAMPTZ,
    review_notes     TEXT,

    is_final         BOOLEAN DEFAULT FALSE,
    superseded_by    UUID REFERENCES
                         decision_trace(id),

    created_at       TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS
    idx_decision_trace_app
    ON decision_trace(application_id, tenant_id);

CREATE INDEX IF NOT EXISTS
    idx_decision_trace_outcome
    ON decision_trace(tenant_id, final_outcome, decided_at);

CREATE INDEX IF NOT EXISTS
    idx_decision_trace_date
    ON decision_trace(tenant_id, decided_at DESC);

-- One trace per decision generation (the decision_outputs row it summarizes).
-- Makes build_and_save idempotent within a decision generation; a rerun that
-- writes new decision_outputs rows (new id) yields a new trace.
CREATE UNIQUE INDEX IF NOT EXISTS
    uq_decision_trace_decision
    ON decision_trace(decision_id)
    WHERE decision_id IS NOT NULL;


-- ─────────────────────────────────────────────
-- DECISION_AUDIT_LOG
-- Every action on a decision. Append-only.
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS decision_audit_log (
    id               UUID DEFAULT gen_random_uuid()
                     PRIMARY KEY,
    application_id   VARCHAR(50) NOT NULL,
    tenant_id        VARCHAR(50) NOT NULL,
    trace_id         UUID REFERENCES
                         decision_trace(id),

    action           VARCHAR(50) NOT NULL
                     CHECK (action IN (
                         'decision_created',
                         'decision_reviewed',
                         'condition_created',
                         'condition_satisfied',
                         'condition_waived',
                         'outcome_override',
                         'exception_approved',
                         'document_received',
                         'escalated_to_uw',
                         'loan_closed',
                         'loan_denied',
                         'loan_withdrawn'
                     )),

    actor            VARCHAR(100) NOT NULL,
    actor_role       VARCHAR(50),
    details          JSONB DEFAULT '{}',
    ip_address       VARCHAR(45),
    created_at       TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS
    idx_audit_log_app
    ON decision_audit_log(application_id, tenant_id);

CREATE INDEX IF NOT EXISTS
    idx_audit_log_date
    ON decision_audit_log(tenant_id, created_at DESC);


-- RLS — both tables read-only for tenants
ALTER TABLE decision_trace
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE decision_audit_log
    ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
  DROP POLICY IF EXISTS dt_read ON decision_trace;
  CREATE POLICY dt_read ON decision_trace
      FOR SELECT USING (
          tenant_id = current_setting('app.tenant_id', true)
          OR current_user = 'edms_admin'
      );
  DROP POLICY IF EXISTS dt_insert ON decision_trace;
  CREATE POLICY dt_insert ON decision_trace
      FOR INSERT WITH CHECK (true);
  DROP POLICY IF EXISTS dt_update ON decision_trace;
  CREATE POLICY dt_update ON decision_trace
      FOR UPDATE USING (current_user = 'edms_admin');

  DROP POLICY IF EXISTS dal_read ON decision_audit_log;
  CREATE POLICY dal_read ON decision_audit_log
      FOR SELECT USING (
          tenant_id = current_setting('app.tenant_id', true)
          OR current_user = 'edms_admin'
      );
  DROP POLICY IF EXISTS dal_insert ON decision_audit_log;
  CREATE POLICY dal_insert ON decision_audit_log
      FOR INSERT WITH CHECK (true);
END $$;

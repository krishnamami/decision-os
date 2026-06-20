-- scripts/migrations/create_loan_conditions.sql
-- CN-A — live, resolver-driven condition instances on specific loans.
--
-- NB on naming: the table name `loan_conditions` is already taken by the
-- underwriter workbench (create_workbench_tables.sql — different schema:
-- condition_id PK / condition_type ptc/ptd/ptf / assigned_to UUID, with live
-- rows + UI/API consumers). The resolver-driven conditions engine therefore
-- uses `loan_condition_instances` to avoid clobbering the workbench table.

-- ─────────────────────────────────────────────
-- LOAN_CONDITION_INSTANCES
-- Live condition instances on specific loans.
-- One row per condition per loan.
-- Populated when resolvers generate conditions.
-- Cleared when docs received + UW approves.
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS loan_condition_instances (
    id               UUID DEFAULT gen_random_uuid()
                     PRIMARY KEY,
    application_id   VARCHAR(50) NOT NULL,
    tenant_id        VARCHAR(50) NOT NULL,

    -- Link to template
    condition_code   VARCHAR(100) NOT NULL,
    category         VARCHAR(50) NOT NULL,

    -- Condition text (filled from template)
    condition_text   TEXT NOT NULL,
    agency_citation  TEXT,

    -- Status lifecycle
    status           VARCHAR(20) NOT NULL
                     DEFAULT 'open'
                     CHECK (status IN (
                         'open',
                         'submitted',
                         'in_review',
                         'approved',
                         'waived',
                         'rejected'
                     )),

    -- Timing
    prior_to         VARCHAR(20) NOT NULL
                     CHECK (prior_to IN (
                         'docs',
                         'closing',
                         'funding'
                     )),
    sla_hours        INTEGER DEFAULT 48,
    due_date         TIMESTAMPTZ,
    opened_at        TIMESTAMPTZ DEFAULT NOW(),
    submitted_at     TIMESTAMPTZ,
    cleared_at       TIMESTAMPTZ,

    -- Assignment
    assignee         VARCHAR(20) DEFAULT 'borrower'
                     CHECK (assignee IN (
                         'borrower',
                         'lender',
                         'title',
                         'appraiser'
                     )),
    assigned_to_name VARCHAR(200),

    -- Document requirement
    edms_document_type VARCHAR(100),
    satisfying_doc_id  VARCHAR(100),

    -- Blocking flag
    blocks_closing   BOOLEAN DEFAULT FALSE,
    auto_satisfy     BOOLEAN DEFAULT FALSE,

    -- Source
    generated_by     VARCHAR(100),
    decision_id      UUID,
    notes            TEXT,

    created_at       TIMESTAMPTZ DEFAULT NOW(),
    updated_at       TIMESTAMPTZ DEFAULT NOW(),

    -- Prevent exact duplicates per loan
    UNIQUE(application_id, tenant_id,
           condition_code)
);

CREATE INDEX IF NOT EXISTS
    idx_loan_cond_inst_app
    ON loan_condition_instances(application_id, tenant_id);

CREATE INDEX IF NOT EXISTS
    idx_loan_cond_inst_status
    ON loan_condition_instances(
        application_id, status
    )
    WHERE status IN ('open','submitted','in_review');

CREATE INDEX IF NOT EXISTS
    idx_loan_cond_inst_blocking
    ON loan_condition_instances(application_id, blocks_closing)
    WHERE blocks_closing = TRUE
    AND status NOT IN ('approved','waived');


-- ─────────────────────────────────────────────
-- CONDITION_DOCUMENTS
-- Documents submitted to satisfy a condition.
-- One row per document per condition.
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS condition_documents (
    id               UUID DEFAULT gen_random_uuid()
                     PRIMARY KEY,
    condition_id     UUID NOT NULL
                     REFERENCES loan_condition_instances(id)
                     ON DELETE CASCADE,
    application_id   VARCHAR(50) NOT NULL,
    tenant_id        VARCHAR(50) NOT NULL,
    document_id      VARCHAR(100),
    document_type    VARCHAR(100),
    submitted_at     TIMESTAMPTZ DEFAULT NOW(),
    reviewed_by      VARCHAR(100),
    review_notes     TEXT,
    satisfies        BOOLEAN DEFAULT FALSE,
    created_at       TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS
    idx_condition_docs_condition
    ON condition_documents(condition_id);


-- RLS
ALTER TABLE loan_condition_instances
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE condition_documents
    ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
  DROP POLICY IF EXISTS lci_read ON loan_condition_instances;
  CREATE POLICY lci_read ON loan_condition_instances
      FOR SELECT USING (
          tenant_id = current_setting(
              'app.tenant_id', true
          ) OR current_user = 'edms_admin'
      );
  DROP POLICY IF EXISTS lci_write ON loan_condition_instances;
  CREATE POLICY lci_write ON loan_condition_instances
      FOR INSERT WITH CHECK (true);
  DROP POLICY IF EXISTS lci_update ON loan_condition_instances;
  CREATE POLICY lci_update ON loan_condition_instances
      FOR UPDATE USING (
          current_user = 'edms_admin'
          OR current_user = 'governance_admin'
      );

  DROP POLICY IF EXISTS cd_read
      ON condition_documents;
  CREATE POLICY cd_read ON condition_documents
      FOR SELECT USING (
          tenant_id = current_setting(
              'app.tenant_id', true
          ) OR current_user = 'edms_admin'
      );
  DROP POLICY IF EXISTS cd_write
      ON condition_documents;
  CREATE POLICY cd_write ON condition_documents
      FOR INSERT WITH CHECK (true);
END $$;

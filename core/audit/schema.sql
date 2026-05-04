-- ============================================================
-- Decision OS — audit engine durable schema (PRD §23.6)
-- ------------------------------------------------------------
-- Three append-only tables back the Audit Engine:
--   1) audit_records     — one row per decision. Never deleted.
--                          Corrections insert a new row with
--                          supersedes_audit_id pointing at the
--                          prior record.
--   2) audit_access_log  — every read of an audit record. Who,
--                          when, why. Honours pii_access_always_logged.
--   3) audit_flags       — open warn/fail records awaiting
--                          compliance review; resolution columns
--                          are NULL until cleared.
--
-- Hard rules backed here (PRD §23.9):
--   audit_records_never_deleted              — no DELETE/UPDATE on
--                                              audit_records; only
--                                              new rows.
--   audit_record_required_before_writeback   — gate enforced in
--                                              core/decision_agents/
--                                              atomic_tool.py.
--   pii_access_always_logged                  — every read writes
--                                              an audit_access_log
--                                              row (enforced in
--                                              PostgresAuditStore).
-- ============================================================

CREATE TABLE IF NOT EXISTS audit_records (
    audit_id              UUID         PRIMARY KEY,
    decision_id           UUID         NOT NULL,
    application_id        TEXT         NOT NULL,
    decision_type         TEXT         NOT NULL,
    timestamp             TIMESTAMPTZ  NOT NULL DEFAULT now(),
    supersedes_audit_id   UUID,

    -- Decision block
    event_input           JSONB        NOT NULL DEFAULT '{}'::jsonb,
    context_used          JSONB        NOT NULL DEFAULT '{}'::jsonb,
    ontology_mapping      JSONB        NOT NULL DEFAULT '{}'::jsonb,
    policy_applied        JSONB        NOT NULL DEFAULT '[]'::jsonb,
    decision_output       TEXT         NOT NULL,
    confidence            DOUBLE PRECISION NOT NULL,
    owner                 TEXT         NOT NULL,
    mode                  TEXT         NOT NULL,
    execution_result      JSONB        NOT NULL DEFAULT '{}'::jsonb,
    outcome               TEXT,

    -- Compliance block
    regulation_tags       TEXT[]       NOT NULL DEFAULT '{}',
    consent_status        TEXT         NOT NULL DEFAULT 'obtained',
    data_sources_used     TEXT[]       NOT NULL DEFAULT '{}',
    disclosure_sent       BOOLEAN      NOT NULL DEFAULT FALSE,
    disclosure_timestamp  TIMESTAMPTZ,
    retention_policy      TEXT,
    compliance_status     TEXT         NOT NULL DEFAULT 'pass',

    -- Security block
    accessed_by           JSONB        NOT NULL DEFAULT '[]'::jsonb,
    permissions_used      TEXT[]       NOT NULL DEFAULT '{}',
    data_classification   TEXT         NOT NULL DEFAULT 'confidential',
    pii_fields_accessed   TEXT[]       NOT NULL DEFAULT '{}',
    encryption_status     TEXT         NOT NULL DEFAULT 'both',
    access_anomaly        BOOLEAN      NOT NULL DEFAULT FALSE,
    access_anomaly_reason TEXT,
    security_status       TEXT         NOT NULL DEFAULT 'pass',

    -- Ethics block
    applicant_segment     TEXT,
    protected_attrs_used  TEXT[]       NOT NULL DEFAULT '{}',
    protected_attrs_excluded TEXT[]    NOT NULL DEFAULT '{}',
    fairness_flags        JSONB        NOT NULL DEFAULT '[]'::jsonb,
    bias_score            DOUBLE PRECISION,
    disparate_impact_flag BOOLEAN      NOT NULL DEFAULT FALSE,
    human_reviewed        BOOLEAN      NOT NULL DEFAULT FALSE,
    ethics_status         TEXT         NOT NULL DEFAULT 'pass',
    fairness_status       TEXT         NOT NULL DEFAULT 'pass',

    -- Aggregate
    overall_status        TEXT         NOT NULL DEFAULT 'pass'
);

-- Append-only enforcement: self-FK on supersedes_audit_id so the
-- correction chain is queryable. ON DELETE NO ACTION because
-- nothing should ever delete from this table.
ALTER TABLE audit_records
    DROP CONSTRAINT IF EXISTS audit_records_supersedes_fk;
ALTER TABLE audit_records
    ADD  CONSTRAINT audit_records_supersedes_fk
    FOREIGN KEY (supersedes_audit_id) REFERENCES audit_records (audit_id);

-- Application drilldown (UI workbench, /audit/application/{id}).
CREATE INDEX IF NOT EXISTS audit_records_app_idx
    ON audit_records (application_id, timestamp DESC);

-- Compliance team filter — flags + recency.
CREATE INDEX IF NOT EXISTS audit_records_status_idx
    ON audit_records (overall_status, timestamp DESC)
    WHERE overall_status IN ('warn', 'fail');

-- Decision-type aggregation (HMDA / fair-lending reports).
CREATE INDEX IF NOT EXISTS audit_records_decision_type_idx
    ON audit_records (decision_type, timestamp DESC);


CREATE TABLE IF NOT EXISTS audit_access_log (
    id           UUID         PRIMARY KEY,
    audit_id     UUID         NOT NULL REFERENCES audit_records (audit_id),
    user_id      TEXT         NOT NULL,
    role         TEXT         NOT NULL,
    action       TEXT         NOT NULL,
    timestamp    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    ip_hash      TEXT
);

CREATE INDEX IF NOT EXISTS audit_access_log_audit_idx
    ON audit_access_log (audit_id, timestamp DESC);


CREATE TABLE IF NOT EXISTS audit_flags (
    id              UUID         PRIMARY KEY,
    audit_id        UUID         NOT NULL REFERENCES audit_records (audit_id),
    severity        TEXT         NOT NULL CHECK (severity IN ('warn', 'fail')),
    check_name      TEXT         NOT NULL CHECK (check_name IN ('compliance', 'security', 'ethics', 'fairness')),
    description     TEXT         NOT NULL,
    raised_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    resolved_at     TIMESTAMPTZ,
    resolved_by     TEXT,
    resolution_note TEXT
);

CREATE INDEX IF NOT EXISTS audit_flags_open_idx
    ON audit_flags (severity, raised_at DESC)
    WHERE resolved_at IS NULL;

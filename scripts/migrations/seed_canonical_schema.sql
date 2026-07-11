-- scripts/migrations/seed_canonical_schema.sql
-- P21a: Canonical Schema Registry — static source of truth for all valid
-- entity.column pairs in loan origination scope.
CREATE TABLE IF NOT EXISTS canonical_schema_registry (
    id                  SERIAL PRIMARY KEY,
    entity              VARCHAR(50)  NOT NULL,
    column_name         VARCHAR(100) NOT NULL,
    display_name        VARCHAR(150) NOT NULL,
    es_column           VARCHAR(100),
    jsonb_path          VARCHAR(200),
    data_type           VARCHAR(30)  NOT NULL DEFAULT 'text',
    persona_scope       VARCHAR(200),
    source_doc_type     VARCHAR(200),
    encompass_field_id  VARCHAR(20),
    is_required         BOOLEAN      NOT NULL DEFAULT FALSE,
    notes               TEXT,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (entity, column_name)
);
CREATE INDEX IF NOT EXISTS idx_csr_entity ON canonical_schema_registry(entity);
CREATE INDEX IF NOT EXISTS idx_csr_required ON canonical_schema_registry(is_required) WHERE is_required = TRUE;

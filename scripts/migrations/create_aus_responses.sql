-- RA-AUS-A: aus_responses — parsed AUS (DU / LP) recommendations.
-- One row per application per tenant per AUS system. parsed_response holds the
-- full DUParser output; the scalar columns are denormalized for querying.
-- Population is via core.aus.store.ingest_du_response (future MISMO adapter).
-- Additive — no existing table or row is touched.

CREATE TABLE IF NOT EXISTS aus_responses (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    application_id     TEXT NOT NULL,
    tenant_id          TEXT NOT NULL,
    aus_system         TEXT NOT NULL,
    recommendation     TEXT NOT NULL,
    raw_recommendation TEXT,
    approve            BOOLEAN,
    eligible           BOOLEAN,
    risk_class         TEXT,
    findings           JSONB DEFAULT '[]',
    conditions         JSONB DEFAULT '[]',
    casefile_id        TEXT,
    submission_date    DATE,
    parsed_response    JSONB,
    created_at         TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(application_id, tenant_id, aus_system)
);

CREATE INDEX IF NOT EXISTS idx_aus_application
    ON aus_responses(application_id, tenant_id);

-- RA-7C: hmda_lar — HMDA Loan/Application Register (Reg C, 12 CFR Part 1003).
-- One row per application per tenant. Loan data + action taken + applicant
-- demographic data (collected and reported; NEVER used in underwriting).
-- Population is a downstream job reading underwriting_decision outputs (the
-- persona emits the LAR record into decision_outputs.context_snapshot.hmda_lar).
-- Additive — no existing table or row is touched.

CREATE TABLE IF NOT EXISTS hmda_lar (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    application_id      TEXT NOT NULL,
    tenant_id           TEXT NOT NULL,
    action_taken        INTEGER NOT NULL,
    action_taken_date   DATE,
    loan_type           TEXT,
    loan_purpose        TEXT,
    loan_amount         NUMERIC,
    interest_rate       NUMERIC,
    loan_term_months    INTEGER,
    property_type       TEXT,
    occupancy_type      TEXT,
    state_code          TEXT,
    county_code         TEXT,
    census_tract        TEXT,
    lien_status         INTEGER DEFAULT 1,
    applicant_income    NUMERIC,
    applicant_ethnicity INTEGER DEFAULT 3,   -- FFIEC: info not provided
    applicant_race      INTEGER DEFAULT 6,   -- FFIEC: info not provided
    applicant_sex       INTEGER DEFAULT 3,   -- FFIEC: info not provided
    applicant_age       INTEGER,
    denial_reasons      INTEGER[],
    aus_result          TEXT,
    aus_system          TEXT,
    hmda_reportable     BOOLEAN DEFAULT TRUE,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(application_id, tenant_id)
);

CREATE INDEX IF NOT EXISTS idx_hmda_lar_tenant_action
    ON hmda_lar(tenant_id, action_taken);

-- scripts/migrations/create_conditions_library.sql
-- TL-E — central library of standard underwriting conditions. One row per
-- condition type. Personas (title_assessment first) map their generated codes
-- to rows here to produce filled, citable conditions with SLA + assignee.

CREATE TABLE IF NOT EXISTS conditions_library (
    id              UUID DEFAULT gen_random_uuid()
                    PRIMARY KEY,
    code            VARCHAR(100) NOT NULL UNIQUE,
    category        VARCHAR(50) NOT NULL
                    CHECK (category IN (
                        'title', 'income', 'asset',
                        'credit', 'employment',
                        'compliance', 'fraud',
                        'property', 'closing',
                        'product'
                    )),
    template_text   TEXT NOT NULL,
    agency_citation TEXT,
    prior_to        VARCHAR(20) NOT NULL
                    CHECK (prior_to IN (
                        'docs', 'closing', 'funding'
                    )),
    sla_hours       INTEGER DEFAULT 48,
    assignee        VARCHAR(20) DEFAULT 'borrower'
                    CHECK (assignee IN (
                        'borrower', 'lender',
                        'title', 'appraiser'
                    )),
    edms_document_type VARCHAR(100),
    auto_satisfy    BOOLEAN DEFAULT FALSE,
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

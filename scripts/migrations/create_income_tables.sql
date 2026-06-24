-- INC-A: income entity model — income_sources + employment_history + gap view.
--
-- entity_states.qualifying_monthly is a single scalar and cannot represent
-- multiple income streams, per-stream history/evidence, or co-borrower
-- separation. income_sources fixes that (one row per income stream per
-- borrower); employment_history holds per-job history for gap detection.
--
-- ADDITIVE — entity_states.qualifying_monthly stays populated for the 14
-- personas. No RLS yet (INC-B adds tenant policy). All idempotent.

-- ── income_sources ──────────────────────────────────────────────────────
-- income_type values: W2 / HOURLY / SELF_EMPLOYED / RENTAL / RETIREMENT /
--   SOCIAL_SECURITY / ASSET_DEPLETION / ALIMONY / CHILD_SUPPORT / OTHER
-- borrower_role values: primary / co_borrower / non_occupant
CREATE TABLE IF NOT EXISTS income_sources (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    application_id      TEXT NOT NULL,
    tenant_id           TEXT NOT NULL,
    borrower_role       TEXT NOT NULL DEFAULT 'primary',
    income_type         TEXT NOT NULL,
    income_subtype      TEXT,
    employer_name       TEXT,
    monthly_amount      NUMERIC NOT NULL DEFAULT 0,
    annual_amount       NUMERIC GENERATED ALWAYS AS (monthly_amount * 12) STORED,
    frequency           TEXT DEFAULT 'monthly',
    start_date          DATE,
    end_date            DATE,
    is_current          BOOLEAN DEFAULT TRUE,
    confidence          NUMERIC DEFAULT 0.0,
    method              TEXT,
    fact_node_ids       UUID[],
    doc_references      TEXT[],
    notes               TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_income_application
    ON income_sources(application_id, tenant_id);
CREATE INDEX IF NOT EXISTS idx_income_role
    ON income_sources(application_id, tenant_id, borrower_role);
CREATE INDEX IF NOT EXISTS idx_income_type
    ON income_sources(application_id, tenant_id, income_type);

-- ── employment_history ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS employment_history (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    application_id      TEXT NOT NULL,
    tenant_id           TEXT NOT NULL,
    borrower_role       TEXT NOT NULL DEFAULT 'primary',
    employer_name       TEXT NOT NULL,
    position            TEXT,
    employment_type     TEXT DEFAULT 'W2',
    start_date          DATE NOT NULL,
    end_date            DATE,
    is_current          BOOLEAN DEFAULT FALSE,
    monthly_income      NUMERIC DEFAULT 0,
    state               TEXT,
    is_self_employed    BOOLEAN DEFAULT FALSE,
    ownership_pct       NUMERIC,
    income_source_id    UUID REFERENCES income_sources(id),
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_emp_application
    ON employment_history(application_id, tenant_id);

-- ── vw_employment_gaps: gaps > 30 days between consecutive jobs ───────────
-- Fannie requires a written explanation for employment gaps > 30 days; this
-- view feeds the employment_reconciliation persona.
CREATE OR REPLACE VIEW vw_employment_gaps AS
SELECT
    e1.application_id,
    e1.tenant_id,
    e1.borrower_role,
    e1.employer_name AS from_employer,
    e2.employer_name AS to_employer,
    e1.end_date      AS gap_start,
    e2.start_date    AS gap_end,
    (e2.start_date - e1.end_date) AS gap_days
FROM employment_history e1
JOIN employment_history e2
    ON e1.application_id = e2.application_id
    AND e1.tenant_id     = e2.tenant_id
    AND e1.borrower_role = e2.borrower_role
    AND e2.start_date > e1.end_date
WHERE (e2.start_date - e1.end_date) > 30
ORDER BY e1.application_id, e1.end_date;

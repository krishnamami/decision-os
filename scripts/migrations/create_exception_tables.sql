-- EX-A: structured exception framework + compensating factors.
--
-- Builds ON the existing override capture (loan_actions + decision_outputs.human_*)
-- — does NOT duplicate it. loan_exceptions formalizes the request → review → grant
-- lifecycle and links back to the decision_output + loan_action that recorded the
-- human override; compensating_factors holds per-factor detail per exception.
-- Additive; advisory (no persona writes these in EX-A — EX-B/C populate them).

CREATE TABLE IF NOT EXISTS loan_exceptions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    application_id      TEXT NOT NULL,
    tenant_id           TEXT NOT NULL,
    decision_output_id  UUID REFERENCES decision_outputs(id),
    loan_action_id      UUID REFERENCES loan_actions(id),
    exception_type      TEXT NOT NULL,      -- dti_overlay_breach / ltv_overlay_breach /
                                            -- credit_overlay_breach / aus_conflict /
                                            -- manual_underwrite / other
    blocked_persona     TEXT NOT NULL,
    blocked_signal      TEXT NOT NULL,
    blocked_value       NUMERIC,
    threshold_value     NUMERIC,
    threshold_source    TEXT,
    breach_pct          NUMERIC,
    below_agency_floor  BOOLEAN DEFAULT FALSE,
    status              TEXT DEFAULT 'requested',  -- requested → under_review → granted/denied
    requested_by        TEXT,
    requested_at        TIMESTAMPTZ DEFAULT NOW(),
    reviewed_by         TEXT,
    reviewed_at         TIMESTAMPTZ,
    granted             BOOLEAN,
    denial_reason       TEXT,
    compensating_factors JSONB DEFAULT '[]',
    notes               TEXT,
    tenant_id_rls       TEXT GENERATED ALWAYS AS (tenant_id) STORED,  -- RLS prep (INC/EX-later)
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_exc_application
    ON loan_exceptions(application_id, tenant_id);
CREATE INDEX IF NOT EXISTS idx_exc_status
    ON loan_exceptions(tenant_id, status)
    WHERE status IN ('requested', 'under_review');

CREATE TABLE IF NOT EXISTS compensating_factors (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    exception_id        UUID NOT NULL REFERENCES loan_exceptions(id),
    application_id      TEXT NOT NULL,
    tenant_id           TEXT NOT NULL,
    factor_type         TEXT NOT NULL,      -- low_ltv / substantial_reserves /
                                            -- minimal_payment_shock / excellent_credit /
                                            -- long_employment / limited_debt /
                                            -- large_down_payment / high_residual_income / other
    factor_value        TEXT,
    factor_numeric      NUMERIC,
    threshold_met       BOOLEAN,
    evidence_source     TEXT,
    citation            TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_compfactor_exception
    ON compensating_factors(exception_id);

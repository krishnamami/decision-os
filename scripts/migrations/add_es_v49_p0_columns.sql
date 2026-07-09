-- scripts/migrations/add_es_v49_p0_columns.sql
-- v4.9 — entity_states P0 canonical columns for Capital Loans onboarding.
-- Same pattern as create_credit_entities.sql (v4.8): standalone, idempotent,
-- additive. The decision engine reads these fields; this gives them typed
-- columns. Already applied to prod RDS `edms` (2026-07); this file is the repo
-- mirror + re-runnable provisioning for fresh environments.
--
-- Change set (all applied together):
--   1. 10 nullable columns on entity_states (below) + 3 partial indexes.
--   2. 3 persona views extended via CREATE OR REPLACE (append-at-end, so the
--      accord_app grant is preserved — NOT DROP+CREATE):
--        vw_product_eligibility_context  += amortization_type, lien_position,
--                                            residual_income, aus_submission_count,
--                                            manual_review_required
--        vw_credit_assessment_context    += credit_report_date, public_records_count,
--                                            inquiries_last_90
--        vw_compliance_check_context     += action_taken, lien_status_hmda
--   3. field_mapping_registry: Encompass source mappings for summit + capital_loans
--        1041->amortization_type (skipped for summit: 1041 already maps to loan_type),
--        420->lien_position, 1569->credit_report_date, 1292->residual_income.
--      (action_taken has no Encompass source — derived in golden_record_writer.)
--   4. Population logic: core/pipeline/golden_record_builder.py (amortization_type,
--      lien_position, lien_status_hmda) + golden_record_writer.py (the 7 DB-derived).

-- ─────────────────────────────────────────────
-- 1. P0 canonical columns (all nullable, additive)
-- ─────────────────────────────────────────────
ALTER TABLE entity_states
    ADD COLUMN IF NOT EXISTS amortization_type      VARCHAR,       -- fixed/arm/balloon/interest_only; product_eligibility ARM routing; loan_terms.urla; Encompass 1041
    ADD COLUMN IF NOT EXISTS lien_position          VARCHAR,       -- first/second/third; CLTV + HELOC eligibility; loan_terms.lien_position; Encompass 420
    ADD COLUMN IF NOT EXISTS credit_report_date     DATE,          -- 120-day staleness at closing; credit_profiles.report_date; Encompass 1569
    ADD COLUMN IF NOT EXISTS public_records_count   INTEGER,       -- BK/judgment waiting period; credit_profiles.profile_data JSONB
    ADD COLUMN IF NOT EXISTS inquiries_last_90      INTEGER,       -- thin-file + fraud signal; credit_profiles.profile_data JSONB (last 90d)
    ADD COLUMN IF NOT EXISTS residual_income        NUMERIC(12,2), -- VA regional minimum; qualifying_monthly - obligations - property expense; Encompass 1292
    ADD COLUMN IF NOT EXISTS action_taken           VARCHAR,       -- HMDA LAR; compliance_check reads; derived from decision status
    ADD COLUMN IF NOT EXISTS lien_status_hmda       VARCHAR,       -- HMDA LAR; compliance_check reads; from lien_position (NULL when unknown)
    ADD COLUMN IF NOT EXISTS aus_submission_count   INTEGER,       -- Day-1 Certainty; COUNT(*) from aus_results
    ADD COLUMN IF NOT EXISTS manual_review_required BOOLEAN;       -- AUS manual downgrade -> senior UW; aus_results recommendation 'refer'

-- ─────────────────────────────────────────────
-- 2. Partial indexes (only searchable-standalone fields; the rest are filtered
--    via joins, not standalone queries)
-- ─────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_es_amort_type
    ON entity_states(amortization_type)      WHERE amortization_type IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_es_action_taken
    ON entity_states(action_taken)           WHERE action_taken IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_es_manual_review
    ON entity_states(manual_review_required) WHERE manual_review_required = true;

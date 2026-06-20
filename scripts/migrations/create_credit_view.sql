-- scripts/migrations/create_credit_view.sql  (CR-E)
-- Extends vw_credit_assessment_context with tradeline + findings rollups from
-- the CR-A entity tables. All pre-existing columns are preserved verbatim and
-- in their original order (CREATE OR REPLACE VIEW can only APPEND columns), so
-- the credit_assessment field_map keeps working; the 4 new columns are added
-- at the end.

CREATE OR REPLACE VIEW vw_credit_assessment_context AS
SELECT
    es.application_id,
    es.tenant_id,
    es.borrower ->> 'applicant_id'                                        AS applicant_id,
    ((es.borrower -> 'credit') ->> 'mid_score')::integer                  AS credit_score,
    (es.borrower -> 'credit') ->> 'credit_band'                          AS credit_band,
    ((es.borrower -> 'credit') ->> 'equifax_score')::integer             AS equifax_score,
    ((es.borrower -> 'credit') ->> 'experian_score')::integer           AS experian_score,
    ((es.borrower -> 'credit') ->> 'transunion_score')::integer         AS transunion_score,
    ((es.borrower -> 'credit') ->> 'active_bankruptcy')::boolean         AS active_bankruptcy,
    ((es.borrower -> 'credit') ->> 'foreclosure_last_36_months')::boolean AS foreclosure_last_36_months,
    ((es.borrower -> 'credit') ->> 'thin_file')::boolean                 AS thin_file,
    ((es.borrower -> 'credit') ->> 'no_derogatory_last_24_months')::boolean AS no_derogatory_last_24_months,
    ((es.borrower -> 'credit') ->> 'derogatory_marks')::integer          AS derogatory_marks,
    ((es.borrower -> 'credit') ->> 'open_tradelines')::integer           AS open_tradelines,
    ((es.borrower -> 'credit') ->> 'credit_utilization')::double precision AS credit_utilization,
    CASE
        WHEN jsonb_typeof((es.borrower -> 'credit') -> 'monthly_obligations') = 'number'
            THEN ((es.borrower -> 'credit') ->> 'monthly_obligations')::double precision
        WHEN jsonb_typeof((es.borrower -> 'credit') -> 'monthly_obligations') = 'array'
            THEN (SELECT COALESCE(sum((elem.value ->> 'monthly_payment')::double precision), 0::double precision)
                  FROM jsonb_array_elements((es.borrower -> 'credit') -> 'monthly_obligations') elem(value))
        ELSE 0::double precision
    END                                                                  AS monthly_obligations,
    LEAST(
        ((es.borrower -> 'credit') ->> 'mid_score')::integer,
        COALESCE((((es.co_borrowers -> 0) -> 'credit') ->> 'mid_score')::integer,
                 ((es.borrower -> 'credit') ->> 'mid_score')::integer)
    )                                                                    AS governing_credit_score,
    es.status,
    es.completeness_pct,

    -- ── NEW (CR-E): tradeline analysis input ──────────────────────────
    COALESCE((
        SELECT json_agg(json_build_object(
            'creditor_name',     ct.creditor_name,
            'account_type',      ct.account_type,
            'current_balance',   ct.current_balance,
            'monthly_payment',   ct.monthly_payment,
            'payment_status',    ct.payment_status,
            'is_authorized_user',ct.is_authorized_user,
            'is_disputed',       ct.is_disputed,
            'is_medical',        ct.is_medical,
            'student_loan_type', ct.student_loan_type,
            'ibr_payment',       ct.ibr_payment,
            'months_remaining',  ct.months_remaining,
            'late_30_count',     ct.late_30_count,
            'late_60_count',     ct.late_60_count,
            'late_90_count',     ct.late_90_count
        ))
        FROM credit_tradelines ct
        WHERE ct.application_id = es.application_id
          AND ct.tenant_id = es.tenant_id
    ), '[]'::json)                                                       AS tradelines,

    -- ── NEW (CR-E): credit findings ───────────────────────────────────
    COALESCE((
        SELECT json_agg(json_build_object(
            'finding_type',      cf.finding_type,
            'severity',          cf.severity,
            'event_date',        cf.event_date,
            'discharge_date',    cf.discharge_date,
            'amount',            cf.amount,
            'blocks_approval',   cf.blocks_approval,
            'requires_loe',      cf.requires_loe,
            'currently_eligible',cf.currently_eligible
        ))
        FROM credit_findings cf
        WHERE cf.application_id = es.application_id
          AND cf.tenant_id = es.tenant_id
    ), '[]'::json)                                                       AS credit_findings,

    -- ── NEW (CR-E): derogatory count from tradelines ──────────────────
    COALESCE((
        SELECT COUNT(*)
        FROM credit_tradelines ct
        WHERE ct.application_id = es.application_id
          AND ct.tenant_id = es.tenant_id
          AND ct.payment_status NOT IN ('current', 'paid', 'unknown')
    ), 0)                                                                AS derogatory_tradeline_count,

    -- ── NEW (CR-E): disputed derogatory count ─────────────────────────
    COALESCE((
        SELECT COUNT(*)
        FROM credit_tradelines ct
        WHERE ct.application_id = es.application_id
          AND ct.tenant_id = es.tenant_id
          AND ct.is_disputed = true
          AND ct.payment_status NOT IN ('current', 'paid', 'unknown')
    ), 0)                                                                AS disputed_derogatory_count

FROM entity_states es;

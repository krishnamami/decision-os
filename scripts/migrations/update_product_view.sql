-- scripts/migrations/update_product_view.sql  (CO-C)
-- Extends vw_product_eligibility_context with collateral inputs (CO-A/CO-B) and
-- a LEFT JOIN to property_eligibility. All pre-existing columns are preserved
-- verbatim and in their original order (CREATE OR REPLACE VIEW can only APPEND
-- columns), so the product_eligibility field_map keeps working.

CREATE OR REPLACE VIEW vw_product_eligibility_context AS
SELECT
    es.application_id,
    es.tenant_id,
    es.dti_back                                                          AS dti_ratio,
    es.ltv                                                               AS ltv_ratio,
    (es.borrower -> 'credit') ->> 'credit_band'                         AS credit_band,
    es.mid_credit_score                                                 AS credit_score,
    COALESCE((es.loan_terms -> 'urla') ->> 'loan_type',
             es.loan_terms ->> 'loan_type')                             AS loan_type,
    es.loan_amount,
    ((es.loan_terms -> 'urla') ->> 'va_entitlement_used')::numeric      AS va_entitlement_used,
    ((es.loan_terms -> 'urla') ->> 'va_entitlement_remaining')::numeric AS va_entitlement_remaining,
    (es.loan_terms -> 'urla') ->> 'loan_purpose'                        AS loan_purpose,
    es.status,

    -- ── NEW (CO-C): collateral inputs from entity_states ──────────────
    (es.loan_terms -> 'urla') ->> 'property_type'                       AS property_type,
    COALESCE((es.loan_terms -> 'urla') ->> 'property_usage_type',
             (es.loan_terms -> 'urla') ->> 'occupancy',
             'primary')                                                 AS usage_type,
    es.purchase_price,
    es.appraised_value,
    es.piti_monthly,

    -- ── NEW (CO-C): property_eligibility join (CO-A resolver output) ───
    pe.fannie_eligible                                                  AS prop_fannie_eligible,
    pe.fha_eligible                                                     AS prop_fha_eligible,
    pe.va_eligible                                                      AS prop_va_eligible,
    pe.is_warrantable                                                   AS prop_is_warrantable,
    pe.in_flood_zone                                                    AS prop_in_flood_zone,
    pe.overall_status                                                   AS prop_eligibility_status,
    pe.ineligibility_reasons                                            AS prop_ineligibility_reasons

FROM entity_states es
LEFT JOIN property_eligibility pe
    ON pe.application_id = es.application_id
   AND pe.tenant_id = es.tenant_id;

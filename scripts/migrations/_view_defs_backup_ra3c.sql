-- RA-3C original view definitions (pre-evidence)
-- restore by running these to revert the wrap.

-- vw_income_verification_context
CREATE OR REPLACE VIEW vw_income_verification_context AS
 SELECT entity_states.application_id,
    entity_states.tenant_id,
    entity_states.borrower ->> 'applicant_id'::text AS applicant_id,
    ((entity_states.borrower -> 'income'::text) ->> 'income_confidence_score'::text)::double precision AS income_confidence_score,
    (entity_states.borrower -> 'income'::text) ->> 'employment_type'::text AS employment_type,
    ((entity_states.borrower -> 'income'::text) ->> 'payroll_verified'::text)::boolean AS payroll_verified,
    (entity_states.borrower -> 'employment'::text) ->> 'reconciliation_status'::text AS reconciliation_status,
    ((entity_states.borrower -> 'income'::text) ->> 'income_discrepancy_pct'::text)::double precision AS income_discrepancy_pct,
    ((entity_states.borrower -> 'income'::text) ->> 'stated_income_annual'::text)::double precision AS stated_income,
    ((entity_states.borrower -> 'income'::text) ->> 'verified_income_annual'::text)::double precision AS verified_income,
    ((entity_states.borrower -> 'income'::text) ->> 'multiple_income_sources'::text)::boolean AS multiple_income_sources,
    (entity_states.borrower -> 'income'::text) ->> 'income_stability'::text AS income_stability,
    (entity_states.borrower -> 'income'::text) ->> 'income_trending'::text AS income_trending,
    ((entity_states.borrower -> 'income'::text) ->> 'overall_confidence'::text)::double precision AS overall_confidence,
    entity_states.status
   FROM entity_states;

-- vw_credit_assessment_context
CREATE OR REPLACE VIEW vw_credit_assessment_context AS
 SELECT es.application_id,
    es.tenant_id,
    es.borrower ->> 'applicant_id'::text AS applicant_id,
    ((es.borrower -> 'credit'::text) ->> 'mid_score'::text)::integer AS credit_score,
    (es.borrower -> 'credit'::text) ->> 'credit_band'::text AS credit_band,
    ((es.borrower -> 'credit'::text) ->> 'equifax_score'::text)::integer AS equifax_score,
    ((es.borrower -> 'credit'::text) ->> 'experian_score'::text)::integer AS experian_score,
    ((es.borrower -> 'credit'::text) ->> 'transunion_score'::text)::integer AS transunion_score,
    ((es.borrower -> 'credit'::text) ->> 'active_bankruptcy'::text)::boolean AS active_bankruptcy,
    ((es.borrower -> 'credit'::text) ->> 'foreclosure_last_36_months'::text)::boolean AS foreclosure_last_36_months,
    ((es.borrower -> 'credit'::text) ->> 'thin_file'::text)::boolean AS thin_file,
    ((es.borrower -> 'credit'::text) ->> 'no_derogatory_last_24_months'::text)::boolean AS no_derogatory_last_24_months,
    ((es.borrower -> 'credit'::text) ->> 'derogatory_marks'::text)::integer AS derogatory_marks,
    ((es.borrower -> 'credit'::text) ->> 'open_tradelines'::text)::integer AS open_tradelines,
    ((es.borrower -> 'credit'::text) ->> 'credit_utilization'::text)::double precision AS credit_utilization,
        CASE
            WHEN jsonb_typeof((es.borrower -> 'credit'::text) -> 'monthly_obligations'::text) = 'number'::text THEN ((es.borrower -> 'credit'::text) ->> 'monthly_obligations'::text)::double precision
            WHEN jsonb_typeof((es.borrower -> 'credit'::text) -> 'monthly_obligations'::text) = 'array'::text THEN ( SELECT COALESCE(sum((elem.value ->> 'monthly_payment'::text)::double precision), 0::double precision) AS "coalesce"
               FROM jsonb_array_elements((es.borrower -> 'credit'::text) -> 'monthly_obligations'::text) elem(value))
            ELSE 0::double precision
        END AS monthly_obligations,
    LEAST(((es.borrower -> 'credit'::text) ->> 'mid_score'::text)::integer, COALESCE((((es.co_borrowers -> 0) -> 'credit'::text) ->> 'mid_score'::text)::integer, ((es.borrower -> 'credit'::text) ->> 'mid_score'::text)::integer)) AS governing_credit_score,
    es.status,
    es.completeness_pct,
    COALESCE(( SELECT json_agg(json_build_object('creditor_name', ct.creditor_name, 'account_type', ct.account_type, 'current_balance', ct.current_balance, 'monthly_payment', ct.monthly_payment, 'payment_status', ct.payment_status, 'is_authorized_user', ct.is_authorized_user, 'is_disputed', ct.is_disputed, 'is_medical', ct.is_medical, 'student_loan_type', ct.student_loan_type, 'ibr_payment', ct.ibr_payment, 'months_remaining', ct.months_remaining, 'late_30_count', ct.late_30_count, 'late_60_count', ct.late_60_count, 'late_90_count', ct.late_90_count)) AS json_agg
           FROM credit_tradelines ct
          WHERE ct.application_id::text = es.application_id::text AND ct.tenant_id::text = es.tenant_id::text), '[]'::json) AS tradelines,
    COALESCE(( SELECT json_agg(json_build_object('finding_type', cf.finding_type, 'severity', cf.severity, 'event_date', cf.event_date, 'discharge_date', cf.discharge_date, 'amount', cf.amount, 'blocks_approval', cf.blocks_approval, 'requires_loe', cf.requires_loe, 'currently_eligible', cf.currently_eligible)) AS json_agg
           FROM credit_findings cf
          WHERE cf.application_id::text = es.application_id::text AND cf.tenant_id::text = es.tenant_id::text), '[]'::json) AS credit_findings,
    COALESCE(( SELECT count(*) AS count
           FROM credit_tradelines ct
          WHERE ct.application_id::text = es.application_id::text AND ct.tenant_id::text = es.tenant_id::text AND (ct.payment_status::text <> ALL (ARRAY['current'::character varying, 'paid'::character varying, 'unknown'::character varying]::text[]))), 0::bigint) AS derogatory_tradeline_count,
    COALESCE(( SELECT count(*) AS count
           FROM credit_tradelines ct
          WHERE ct.application_id::text = es.application_id::text AND ct.tenant_id::text = es.tenant_id::text AND ct.is_disputed = true AND (ct.payment_status::text <> ALL (ARRAY['current'::character varying, 'paid'::character varying, 'unknown'::character varying]::text[]))), 0::bigint) AS disputed_derogatory_count
   FROM entity_states es;

-- vw_asset_verification_context
CREATE OR REPLACE VIEW vw_asset_verification_context AS
 SELECT es.application_id,
    es.tenant_id,
    es.borrower ->> 'applicant_id'::text AS applicant_id,
    ((es.borrower -> 'assets'::text) ->> 'large_deposit_amount'::text)::double precision AS large_deposit_amount,
    ((es.borrower -> 'assets'::text) ->> 'large_deposit_documented'::text)::boolean AS large_deposit_documented,
    ((es.borrower -> 'assets'::text) ->> 'liquid_assets_total'::text)::double precision AS liquid_assets_total,
    ((es.borrower -> 'assets'::text) ->> 'reserves_months'::text)::double precision AS reserves_months,
    ((es.borrower -> 'assets'::text) ->> 'checking_savings'::text)::double precision AS checking_savings,
    ((es.borrower -> 'assets'::text) ->> 'gift_funds'::text)::double precision AS gift_funds,
    ((es.borrower -> 'assets'::text) ->> 'gift_funds_documented'::text)::boolean AS gift_funds_documented,
    es.assets_verified,
    es.total_liquid_assets,
    es.status,
    COALESCE(( SELECT json_agg(json_build_object('id', aa.id, 'institution_name', aa.institution_name, 'account_type', aa.account_type, 'current_balance', aa.current_balance, 'qualifying_factor', aa.qualifying_factor, 'qualifying_amount', aa.qualifying_amount, 'seasoned_days', aa.seasoned_days, 'is_seasoned', aa.is_seasoned, 'is_gift', aa.is_gift, 'gift_documented', aa.gift_documented, 'is_business', aa.is_business, 'business_ownership_pct', aa.business_ownership_pct, 'has_large_deposit', aa.has_large_deposit, 'large_deposit_amount', aa.large_deposit_amount, 'large_deposit_sourced', aa.large_deposit_sourced, 'large_deposit_date', aa.large_deposit_date)) AS json_agg
           FROM asset_accounts aa
          WHERE aa.application_id::text = es.application_id::text AND aa.tenant_id::text = es.tenant_id::text), '[]'::json) AS asset_accounts,
    COALESCE(( SELECT json_agg(json_build_object('id', ad.id, 'deposit_date', ad.deposit_date, 'deposit_amount', ad.deposit_amount, 'is_sourced', ad.is_sourced, 'is_gift', ad.is_gift, 'institution_name', aa2.institution_name, 'deposit_source', ad.deposit_source)) AS json_agg
           FROM asset_deposits ad
             JOIN asset_accounts aa2 ON ad.account_id = aa2.id
          WHERE ad.application_id::text = es.application_id::text AND ad.tenant_id::text = es.tenant_id::text AND ad.is_sourced = false), '[]'::json) AS unsourced_deposits,
    COALESCE(( SELECT sum(aa.qualifying_amount) AS sum
           FROM asset_accounts aa
          WHERE aa.application_id::text = es.application_id::text AND aa.tenant_id::text = es.tenant_id::text), 0::numeric) AS total_qualifying_assets,
    COALESCE(( SELECT count(*) AS count
           FROM asset_deposits ad
          WHERE ad.application_id::text = es.application_id::text AND ad.tenant_id::text = es.tenant_id::text AND ad.is_sourced = false), 0::bigint) AS unsourced_deposit_count,
    es.loan_amount,
    es.piti_monthly,
    es.qualifying_monthly,
    GREATEST(es.purchase_price - es.loan_amount, 0::double precision) AS down_payment_computed
   FROM entity_states es;

-- vw_product_eligibility_context
CREATE OR REPLACE VIEW vw_product_eligibility_context AS
 SELECT es.application_id,
    es.tenant_id,
    es.dti_back AS dti_ratio,
    es.ltv AS ltv_ratio,
    (es.borrower -> 'credit'::text) ->> 'credit_band'::text AS credit_band,
    es.mid_credit_score AS credit_score,
    COALESCE((es.loan_terms -> 'urla'::text) ->> 'loan_type'::text, es.loan_terms ->> 'loan_type'::text) AS loan_type,
    es.loan_amount,
    ((es.loan_terms -> 'urla'::text) ->> 'va_entitlement_used'::text)::numeric AS va_entitlement_used,
    ((es.loan_terms -> 'urla'::text) ->> 'va_entitlement_remaining'::text)::numeric AS va_entitlement_remaining,
    (es.loan_terms -> 'urla'::text) ->> 'loan_purpose'::text AS loan_purpose,
    es.status,
    (es.loan_terms -> 'urla'::text) ->> 'property_type'::text AS property_type,
    COALESCE((es.loan_terms -> 'urla'::text) ->> 'property_usage_type'::text, (es.loan_terms -> 'urla'::text) ->> 'occupancy'::text, 'primary'::text) AS usage_type,
    es.purchase_price,
    es.appraised_value,
    es.piti_monthly,
    pe.fannie_eligible AS prop_fannie_eligible,
    pe.fha_eligible AS prop_fha_eligible,
    pe.va_eligible AS prop_va_eligible,
    pe.is_warrantable AS prop_is_warrantable,
    pe.in_flood_zone AS prop_in_flood_zone,
    pe.overall_status AS prop_eligibility_status,
    pe.ineligibility_reasons AS prop_ineligibility_reasons
   FROM entity_states es
     LEFT JOIN property_eligibility pe ON pe.application_id::text = es.application_id::text AND pe.tenant_id::text = es.tenant_id::text;

-- vw_fraud_screening_context
CREATE OR REPLACE VIEW vw_fraud_screening_context AS
 SELECT es.application_id,
    es.tenant_id,
    es.borrower ->> 'applicant_id'::text AS applicant_id,
    ((es.borrower -> 'identity'::text) ->> 'fraud_score'::text)::double precision AS fraud_score,
    ((es.borrower -> 'identity'::text) ->> 'identity_match_confidence'::text)::double precision AS identity_match_confidence,
    ((es.borrower -> 'identity'::text) ->> 'document_authenticity_score'::text)::double precision AS document_authenticity_score,
    ((es.borrower -> 'identity'::text) ->> 'watchlist_match'::text)::boolean AS watchlist_match,
    ((es.borrower -> 'identity'::text) ->> 'synthetic_identity_flag'::text)::boolean AS synthetic_identity_flag,
    es.status,
    COALESCE(( SELECT json_agg(json_build_object('signal_type', fs.signal_type, 'severity', fs.severity, 'description', fs.description, 'auto_block', fs.auto_block, 'requires_review', fs.requires_review, 'condition_code', fs.condition_code, 'variance_pct', fs.variance_pct, 'detected_value', fs.detected_value, 'expected_value', fs.expected_value, 'resolved', fs.resolved) ORDER BY fs.severity DESC) AS json_agg
           FROM fraud_signals fs
          WHERE fs.application_id::text = es.application_id::text AND fs.tenant_id::text = es.tenant_id::text AND fs.resolved = false), '[]'::json) AS fraud_signal_records,
    COALESCE(( SELECT count(*) AS count
           FROM fraud_signals fs
          WHERE fs.application_id::text = es.application_id::text AND fs.tenant_id::text = es.tenant_id::text AND (fs.severity::text = ANY (ARRAY['high'::character varying, 'critical'::character varying]::text[])) AND fs.resolved = false), 0::bigint) AS high_severity_signal_count,
    COALESCE(( SELECT count(*) AS count
           FROM fraud_signals fs
          WHERE fs.application_id::text = es.application_id::text AND fs.tenant_id::text = es.tenant_id::text AND fs.auto_block = true AND fs.resolved = false), 0::bigint) AS auto_block_signal_count
   FROM entity_states es;

-- vw_compliance_check_context
CREATE OR REPLACE VIEW vw_compliance_check_context AS
 SELECT entity_states.application_id,
    entity_states.tenant_id,
    (entity_states.verifications ->> 'hmda_complete'::text)::boolean AS all_hmda_fields_complete,
    (entity_states.verifications ->> 'no_fair_lending_flags'::text)::boolean AS no_fair_lending_flags,
    (entity_states.verifications ->> 'state_rules_passed'::text)::boolean AS state_rules_passed,
    (entity_states.verifications ->> 'fair_lending_violation'::text)::boolean AS fair_lending_violation,
    (entity_states.verifications ->> 'missing_required_disclosures'::text)::boolean AS missing_required_disclosures,
    (entity_states.verifications ->> 'regulatory_ambiguity'::text)::boolean AS regulatory_ambiguity,
    (entity_states.verifications ->> 'mixed_jurisdiction'::text)::boolean AS mixed_jurisdiction,
    (entity_states.verifications ->> 'minor_data_gap'::text)::boolean AS minor_data_gap,
    (entity_states.loan_terms -> 'urla'::text) ->> 'property_state'::text AS property_state,
    (entity_states.loan_terms -> 'urla'::text) ->> 'loan_purpose'::text AS loan_purpose,
    entity_states.ltv,
    ((entity_states.loan_terms -> 'urla'::text) ->> 'property_state'::text) = 'TX'::text AND ((entity_states.loan_terms -> 'urla'::text) ->> 'loan_purpose'::text) = 'cash_out_refinance'::text AND entity_states.ltv > 80.0::double precision AS tx_cashout_ltv_violation,
    entity_states.completeness_pct,
    entity_states.status
   FROM entity_states;

-- vw_dti_calculation_context
CREATE OR REPLACE VIEW vw_dti_calculation_context AS
 SELECT entity_states.application_id,
    entity_states.tenant_id,
    entity_states.dti_back AS dti,
    entity_states.dti_front,
        CASE
            WHEN jsonb_typeof((entity_states.borrower -> 'credit'::text) -> 'monthly_obligations'::text) = 'number'::text THEN ((entity_states.borrower -> 'credit'::text) ->> 'monthly_obligations'::text)::double precision
            WHEN jsonb_typeof((entity_states.borrower -> 'credit'::text) -> 'monthly_obligations'::text) = 'array'::text THEN ( SELECT COALESCE(sum((elem.value ->> 'monthly_payment'::text)::double precision), 0::double precision) AS "coalesce"
               FROM jsonb_array_elements((entity_states.borrower -> 'credit'::text) -> 'monthly_obligations'::text) elem(value))
            ELSE 0::double precision
        END AS existing_debt_obligations,
    entity_states.piti_monthly AS proposed_payment,
    entity_states.qualifying_monthly,
    entity_states.combined_monthly_income,
    ((entity_states.borrower -> 'income'::text) ->> 'overall_confidence'::text)::double precision AS income_confidence,
    entity_states.loan_amount,
    entity_states.interest_rate,
    entity_states.status
   FROM entity_states;

-- vw_employment_reconciliation_context
CREATE OR REPLACE VIEW vw_employment_reconciliation_context AS
 SELECT entity_states.application_id,
    entity_states.tenant_id,
    entity_states.borrower ->> 'applicant_id'::text AS applicant_id,
    (entity_states.borrower -> 'employment'::text) ->> 'reconciliation_status'::text AS reconciliation_status,
    ((entity_states.borrower -> 'employment'::text) ->> 'continuity_coverage_pct'::text)::double precision AS continuity_coverage_pct,
    ((entity_states.borrower -> 'employment'::text) ->> 'max_gap_days'::text)::integer AS max_gap_days,
    ((entity_states.borrower -> 'employment'::text) ->> 'employer_name_match_confidence'::text)::double precision AS employer_name_match_confidence,
    ((entity_states.borrower -> 'employment'::text) ->> 'stated_vs_verified_drift_pct'::text)::double precision AS stated_vs_verified_drift_pct,
    ((entity_states.borrower -> 'employment'::text) ->> 'employer_on_watchlist'::text)::boolean AS employer_on_watchlist,
    (entity_states.borrower -> 'employment'::text) ->> 'employer_name'::text AS employer_name,
    (entity_states.borrower -> 'employment'::text) ->> 'period_start'::text AS period_start,
    (entity_states.borrower -> 'employment'::text) ->> 'period_end'::text AS period_end,
    (entity_states.borrower -> 'employment'::text) ->> 'employment_status'::text AS employment_status,
        CASE
            WHEN (jsonb_typeof((entity_states.borrower -> 'employment'::text) -> 'income_amount'::text) = ANY (ARRAY['number'::text, 'string'::text])) AND ((entity_states.borrower -> 'employment'::text) ->> 'income_amount'::text) ~ '^-?[0-9]+(\.[0-9]+)?$'::text THEN ((entity_states.borrower -> 'employment'::text) ->> 'income_amount'::text)::double precision
            ELSE NULL::double precision
        END AS gross_amount,
    (entity_states.borrower -> 'income'::text) ->> 'stated_employer'::text AS stated_employer,
    ((entity_states.borrower -> 'income'::text) ->> 'stated_income_annual'::text)::double precision AS stated_income,
    entity_states.status
   FROM entity_states;

-- vw_ltv_assessment_context
CREATE OR REPLACE VIEW vw_ltv_assessment_context AS
 SELECT entity_states.application_id,
    entity_states.tenant_id,
    entity_states.ltv,
    entity_states.appraised_value,
    entity_states.purchase_price,
    entity_states.loan_amount,
    (entity_states.property ->> 'down_payment'::text)::double precision AS down_payment,
    (entity_states.property ->> 'appraisal_disputed'::text)::boolean AS appraisal_disputed,
    (entity_states.property -> 'title'::text) ->> 'title_status'::text AS title_status,
    (entity_states.property ->> 'lien_dispute'::text)::boolean AS lien_dispute,
    (entity_states.borrower -> 'credit'::text) ->> 'credit_band'::text AS credit_band,
    entity_states.status
   FROM entity_states;

-- vw_underwriting_decision_context
CREATE OR REPLACE VIEW vw_underwriting_decision_context AS
 SELECT entity_states.application_id,
    entity_states.tenant_id,
    entity_states.borrower,
    entity_states.co_borrowers,
    entity_states.property,
    entity_states.loan_terms,
    entity_states.verifications,
    entity_states.mid_credit_score,
    entity_states.ltv,
    entity_states.dti_back,
    entity_states.dti_front,
    entity_states.piti_monthly,
    entity_states.qualifying_monthly,
    entity_states.combined_monthly_income,
    entity_states.total_liquid_assets,
    entity_states.loan_amount,
    entity_states.interest_rate,
    entity_states.appraised_value,
    entity_states.purchase_price,
    entity_states.completeness_pct,
    entity_states.status
   FROM entity_states;

-- vw_closing_readiness_context
CREATE OR REPLACE VIEW vw_closing_readiness_context AS
 SELECT entity_states.application_id,
    entity_states.tenant_id,
    (entity_states.verifications ->> 'conditions_cleared'::text)::boolean AS all_conditions_cleared,
    (entity_states.verifications ->> 'cd_timing_compliant'::text)::boolean AS cd_timing_compliant,
    (entity_states.verifications ->> 'title_clear'::text)::boolean AS title_clear,
    (entity_states.verifications ->> 'cd_timing_violation'::text)::boolean AS cd_timing_violation,
    (entity_states.property ->> 'title_defect'::text)::boolean AS title_defect,
    (entity_states.property ->> 'lien_dispute'::text)::boolean AS lien_dispute,
    (entity_states.property ->> 'insurance_gap'::text)::boolean AS insurance_gap,
    (entity_states.verifications ->> 'insurance_bound'::text)::boolean AS insurance_binder,
    entity_states.loan_terms ->> 'cd_sent_at'::text AS closing_disclosure_sent_at,
    (entity_states.loan_terms ->> 'days_until_rate_lock_expiry'::text)::integer AS days_until_rate_lock_expiry,
    entity_states.status
   FROM entity_states;

-- vw_approval_routing_context
CREATE OR REPLACE VIEW vw_approval_routing_context AS
 SELECT entity_states.application_id,
    entity_states.tenant_id,
    entity_states.borrower ->> 'applicant_id'::text AS applicant_id,
    entity_states.status,
    entity_states.completeness_pct
   FROM entity_states;

-- vw_rate_pricing_context
CREATE OR REPLACE VIEW vw_rate_pricing_context AS
 SELECT entity_states.application_id,
    entity_states.tenant_id,
    entity_states.mid_credit_score AS credit_score,
    entity_states.dti_back AS dti_ratio,
    entity_states.ltv AS ltv_ratio,
    entity_states.interest_rate,
    entity_states.loan_terms ->> 'loan_type'::text AS loan_type,
    (entity_states.loan_terms ->> 'rate_within_normal_band'::text)::boolean AS rate_within_normal_band,
    (entity_states.loan_terms ->> 'no_manual_adjustments'::text)::boolean AS no_manual_adjustments_required,
    (entity_states.loan_terms ->> 'rate_exceeds_usury'::text)::boolean AS rate_exceeds_usury_limit,
    (entity_states.loan_terms ->> 'concurrent_rate_lock_conflict'::text)::boolean AS concurrent_rate_lock_conflict,
    (entity_states.loan_terms ->> 'llpa_adjustment'::text)::double precision AS llpa_adjustment,
    (entity_states.loan_terms -> 'rate_lock'::text) ->> 'loan_program'::text AS loan_program,
    entity_states.status
   FROM entity_states;

-- vw_title_assessment_context
CREATE OR REPLACE VIEW vw_title_assessment_context AS
 SELECT es.application_id,
    es.tenant_id,
    (es.verifications ->> 'title_clear'::text)::boolean AS title_clear,
    COALESCE(( SELECT json_agg(json_build_object('lien_type', pe.lien_type, 'lien_holder', pe.lien_holder, 'lien_amount', pe.lien_amount, 'blocks_closing', pe.blocks_closing, 'resolution_method', pe.resolution_method, 'priority', pe.priority) ORDER BY pe.priority) AS json_agg
           FROM property_encumbrances pe
          WHERE pe.application_id::text = es.application_id::text AND pe.tenant_id::text = es.tenant_id::text), '[]'::json) AS encumbrances,
    COALESCE(( SELECT json_agg(json_build_object('finding_type', tf.finding_type, 'severity', tf.severity, 'blocks_closing', tf.blocks_closing, 'description', tf.description)) AS json_agg
           FROM title_findings tf
          WHERE tf.application_id::text = es.application_id::text AND tf.tenant_id::text = es.tenant_id::text), '[]'::json) AS title_findings,
    COALESCE(( SELECT json_agg(oc.owner_name) AS json_agg
           FROM ownership_chain oc
          WHERE oc.application_id::text = es.application_id::text AND oc.tenant_id::text = es.tenant_id::text AND oc.is_borrower = false AND oc.must_sign_docs = true), '[]'::json) AS non_borrower_owners,
    COALESCE(( SELECT count(*) AS count
           FROM property_encumbrances pe
          WHERE pe.application_id::text = es.application_id::text AND pe.tenant_id::text = es.tenant_id::text AND pe.blocks_closing = true), 0::bigint) AS blocking_lien_count,
    COALESCE(( SELECT sum(pe.lien_amount) AS sum
           FROM property_encumbrances pe
          WHERE pe.application_id::text = es.application_id::text AND pe.tenant_id::text = es.tenant_id::text AND pe.blocks_closing = true), 0::numeric) AS total_payoff_required
   FROM entity_states es;

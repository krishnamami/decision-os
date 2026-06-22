-- RA-3E: allow fact_type='fraud_indicator' on fact_nodes.
-- The CHECK constraint enumerated fact types but omitted fraud_indicator
-- (it reserved fraud_risk_score). Recreate the constraint with it added.
-- Idempotent: drop-if-exists then add.

ALTER TABLE fact_nodes DROP CONSTRAINT IF EXISTS fact_nodes_fact_type_check;

ALTER TABLE fact_nodes ADD CONSTRAINT fact_nodes_fact_type_check CHECK (
    (fact_type)::text = ANY (ARRAY[
        'qualifying_income',
        'total_obligations',
        'verified_assets',
        'funds_to_close',
        'governing_credit_score',
        'employment_continuity',
        'property_value',
        'title_clear',
        'fraud_risk_score',
        'fraud_indicator',
        'dti_ratio',
        'ltv_ratio'
    ]::text[])
);

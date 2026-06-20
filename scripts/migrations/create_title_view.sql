-- vw_title_assessment_context (TL-D)
-- Per-application title context for the title_assessment persona: joins
-- entity_states with property_encumbrances / title_findings / ownership_chain.
CREATE OR REPLACE VIEW vw_title_assessment_context AS
SELECT
    es.application_id,
    es.tenant_id,
    (es.verifications->>'title_clear')::boolean AS title_clear,

    COALESCE((
        SELECT json_agg(json_build_object(
            'lien_type',         pe.lien_type,
            'lien_holder',       pe.lien_holder,
            'lien_amount',       pe.lien_amount,
            'blocks_closing',    pe.blocks_closing,
            'resolution_method', pe.resolution_method,
            'priority',          pe.priority
        ) ORDER BY pe.priority NULLS LAST)
        FROM property_encumbrances pe
        WHERE pe.application_id = es.application_id AND pe.tenant_id = es.tenant_id
    ), '[]'::json) AS encumbrances,

    COALESCE((
        SELECT json_agg(json_build_object(
            'finding_type',   tf.finding_type,
            'severity',       tf.severity,
            'blocks_closing', tf.blocks_closing,
            'description',    tf.description
        ))
        FROM title_findings tf
        WHERE tf.application_id = es.application_id AND tf.tenant_id = es.tenant_id
    ), '[]'::json) AS title_findings,

    COALESCE((
        SELECT json_agg(oc.owner_name)
        FROM ownership_chain oc
        WHERE oc.application_id = es.application_id AND oc.tenant_id = es.tenant_id
          AND oc.is_borrower = false AND oc.must_sign_docs = true
    ), '[]'::json) AS non_borrower_owners,

    COALESCE((
        SELECT COUNT(*) FROM property_encumbrances pe
        WHERE pe.application_id = es.application_id AND pe.tenant_id = es.tenant_id
          AND pe.blocks_closing = true
    ), 0) AS blocking_lien_count,

    COALESCE((
        SELECT SUM(pe.lien_amount) FROM property_encumbrances pe
        WHERE pe.application_id = es.application_id AND pe.tenant_id = es.tenant_id
          AND pe.blocks_closing = true
    ), 0) AS total_payoff_required

FROM entity_states es;

-- scripts/migrations/update_fraud_view.sql  (FR-E)
-- Extends vw_fraud_screening_context with the fraud_signals rollup (FR-A..FR-D).
-- All pre-existing columns are preserved verbatim and in their original order
-- (CREATE OR REPLACE VIEW can only APPEND columns), so the fraud_screening
-- field_map keeps working; the 3 new columns are appended.

CREATE OR REPLACE VIEW vw_fraud_screening_context AS
SELECT
    es.application_id,
    es.tenant_id,
    es.borrower ->> 'applicant_id'                                            AS applicant_id,
    ((es.borrower -> 'identity') ->> 'fraud_score')::double precision         AS fraud_score,
    ((es.borrower -> 'identity') ->> 'identity_match_confidence')::double precision AS identity_match_confidence,
    ((es.borrower -> 'identity') ->> 'document_authenticity_score')::double precision AS document_authenticity_score,
    ((es.borrower -> 'identity') ->> 'watchlist_match')::boolean              AS watchlist_match,
    ((es.borrower -> 'identity') ->> 'synthetic_identity_flag')::boolean      AS synthetic_identity_flag,
    es.status,

    -- ── NEW (FR-E): unresolved fraud signals ──────────────────────────
    COALESCE((
        SELECT json_agg(json_build_object(
            'signal_type',    fs.signal_type,
            'severity',       fs.severity,
            'description',    fs.description,
            'auto_block',     fs.auto_block,
            'requires_review',fs.requires_review,
            'condition_code', fs.condition_code,
            'variance_pct',   fs.variance_pct,
            'detected_value', fs.detected_value,
            'expected_value', fs.expected_value,
            'resolved',       fs.resolved
        ) ORDER BY fs.severity DESC)
        FROM fraud_signals fs
        WHERE fs.application_id = es.application_id
          AND fs.tenant_id = es.tenant_id
          AND fs.resolved = false
    ), '[]'::json)                                                           AS fraud_signal_records,

    -- ── NEW (FR-E): high/critical signal count ────────────────────────
    COALESCE((
        SELECT COUNT(*) FROM fraud_signals fs
        WHERE fs.application_id = es.application_id
          AND fs.tenant_id = es.tenant_id
          AND fs.severity IN ('high','critical')
          AND fs.resolved = false
    ), 0)                                                                    AS high_severity_signal_count,

    -- ── NEW (FR-E): auto-block signal count ───────────────────────────
    COALESCE((
        SELECT COUNT(*) FROM fraud_signals fs
        WHERE fs.application_id = es.application_id
          AND fs.tenant_id = es.tenant_id
          AND fs.auto_block = true
          AND fs.resolved = false
    ), 0)                                                                    AS auto_block_signal_count

FROM entity_states es;

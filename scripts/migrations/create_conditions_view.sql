-- scripts/migrations/create_conditions_view.sql  (CN-C)
-- Workbench-facing views over loan_condition_instances (CN-A) joined to the
-- conditions_library templates.

CREATE OR REPLACE VIEW vw_loan_condition_summary AS
SELECT
    lci.id,
    lci.application_id,
    lci.tenant_id,
    lci.condition_code,
    lci.category,
    lci.condition_text,
    lci.status,
    lci.prior_to,
    lci.sla_hours,
    lci.due_date,
    lci.assignee,
    lci.blocks_closing,
    lci.generated_by,
    lci.edms_document_type,
    lci.agency_citation,
    lci.opened_at,
    lci.cleared_at,
    lci.satisfying_doc_id,
    lci.notes,

    -- Days until due
    EXTRACT(EPOCH FROM (lci.due_date - NOW())) / 86400 AS days_until_due,

    -- Overdue flag
    (lci.due_date < NOW()
     AND lci.status IN ('open','submitted','in_review')) AS is_overdue,

    -- Template info from library
    cl.agency_citation AS library_citation,

    -- Document submitted count
    COALESCE((
        SELECT COUNT(*)
        FROM condition_documents cd
        WHERE cd.condition_id = lci.id
    ), 0) AS documents_submitted,

    -- Data-driven workbench fields (appended last so CREATE OR REPLACE VIEW
    -- can add them without reordering existing columns)
    cl.governed_by,
    cl.recommended_action,
    cl.review_area

FROM loan_condition_instances lci
LEFT JOIN conditions_library cl
    ON cl.code = lci.condition_code;


-- Aggregate view per loan
CREATE OR REPLACE VIEW vw_loan_conditions_aggregate AS
SELECT
    application_id,
    tenant_id,
    COUNT(*) AS total_conditions,
    COUNT(*) FILTER (
        WHERE status IN ('open','submitted','in_review')
    ) AS open_conditions,
    COUNT(*) FILTER (
        WHERE blocks_closing = true
        AND status NOT IN ('approved','waived')
    ) AS blocking_conditions,
    COUNT(*) FILTER (
        WHERE status IN ('approved','waived')
    ) AS cleared_conditions,
    COUNT(*) FILTER (
        WHERE due_date < NOW()
        AND status IN ('open','submitted','in_review')
    ) AS overdue_conditions,
    MIN(due_date) AS earliest_due,
    MAX(opened_at) AS last_condition_added
FROM loan_condition_instances
GROUP BY application_id, tenant_id;

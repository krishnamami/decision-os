-- scripts/migrations/seed_property_conditions.sql
-- Standard property conditions. One row per condition type. Includes the
-- data-driven columns (governed_by, recommended_action, review_area) so no
-- backfill is needed. Idempotent via ON CONFLICT (code) DO NOTHING.

INSERT INTO conditions_library (
    code, category, template_text, agency_citation,
    prior_to, sla_hours, assignee, edms_document_type,
    governed_by, recommended_action, review_area
) VALUES

('PROPERTY_APPRAISAL_REQUIRED',
 'property',
 'Full URAR appraisal required — order through approved AMC panel',
 'Fannie Mae B4-1.1-01',
 'docs', 72, 'lender', 'APPRAISAL',
 'agency', 'view_details', 'Property'),

('PROPERTY_APPRAISAL_REVIEW',
 'property',
 'Appraisal value requires field review or desk review before approval',
 'Fannie Mae B4-1.3-04',
 'docs', 48, 'lender', 'APPRAISAL',
 'agency', 'view_details', 'Property'),

('PROPERTY_APPRAISAL_GAP',
 'property',
 'Purchase price exceeds appraised value — borrower must cover gap or renegotiate',
 'Fannie Mae B4-1.3-04',
 'docs', 48, 'borrower', null,
 'agency', 'view_details', 'Property'),

('PROPERTY_CONDO_WARRANTABILITY',
 'property',
 'Condominium project warrantability review required before loan approval',
 'Fannie Mae B4-2.1-01',
 'docs', 72, 'lender', null,
 'agency', 'escalate', 'Property'),

('PROPERTY_FLOOD_DETERMINATION',
 'property',
 'Standard flood zone determination required — order from approved vendor',
 'Fannie Mae B7-3-02 / 42 USC §4012a',
 'docs', 48, 'lender', 'FLOOD_CERT',
 'federal', 'view_details', 'Property'),

('PROPERTY_INELIGIBLE_TYPE',
 'property',
 'Property type may not be eligible — provide documentation for underwriter review',
 'Fannie Mae B2-3-01',
 'docs', 48, 'lender', null,
 'agency', 'escalate', 'Property'),

('PROPERTY_REPAIRS_REQUIRED',
 'property',
 'Appraiser-required repairs must be completed and re-inspected before closing',
 'Fannie Mae B4-1.2-01',
 'closing', 48, 'borrower', null,
 'agency', 'view_details', 'Property'),

('PROPERTY_INSURANCE_ADEQUATE',
 'property',
 'Homeowners insurance coverage must equal replacement cost or loan amount',
 'Fannie Mae B7-3-01',
 'closing', 48, 'borrower', 'HOI_BINDER',
 'agency', 'request_documents', 'Property')

ON CONFLICT (code) DO NOTHING;

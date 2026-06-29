-- scripts/migrations/seed_employment_conditions.sql
-- Standard employment conditions. One row per condition type. Includes the
-- data-driven columns (governed_by, recommended_action, review_area) so no
-- backfill is needed. Idempotent via ON CONFLICT (code) DO NOTHING.

INSERT INTO conditions_library (
    code, category, template_text, agency_citation,
    prior_to, sla_hours, assignee, edms_document_type,
    governed_by, recommended_action, review_area
) VALUES

('EMPLOYMENT_GAP_LOE',
 'employment',
 'Provide written letter of explanation for employment gap exceeding 30 days',
 'Fannie Mae B3-3.1-09',
 'docs', 48, 'borrower', null,
 'agency', 'request_documents', 'Employment'),

('EMPLOYMENT_VOE_CURRENT',
 'employment',
 'Provide verification of employment from current employer confirming position and income',
 'Fannie Mae B3-3.1-07',
 'closing', 24, 'lender', 'VOE',
 'agency', 'request_documents', 'Employment'),

('EMPLOYMENT_VOE_PRIOR',
 'employment',
 'Provide verification of employment from prior employer to complete 2-year history',
 'Fannie Mae B3-3.1-07',
 'docs', 48, 'borrower', 'VOE',
 'agency', 'request_documents', 'Employment'),

('EMPLOYMENT_2YR_HISTORY',
 'employment',
 'Provide documentation to establish 2-year employment history per agency guidelines',
 'Fannie Mae B3-3.1-09 / 12 CFR 1026.43',
 'docs', 48, 'borrower', null,
 'federal', 'request_documents', 'Employment'),

('EMPLOYMENT_SELF_EMPLOYED_2YR',
 'employment',
 'Provide documentation confirming self-employment for minimum 2 years',
 'Fannie Mae B3-3.4-01',
 'docs', 48, 'borrower', null,
 'agency', 'request_documents', 'Employment'),

('EMPLOYMENT_OFFER_LETTER',
 'employment',
 'Provide signed offer letter confirming start date, position, and salary for new employment',
 'Fannie Mae B3-3.1-09',
 'docs', 48, 'borrower', null,
 'agency', 'request_documents', 'Employment'),

('EMPLOYMENT_MISMATCH_EXPLANATION',
 'employment',
 'Provide written explanation for employer name mismatch across W2 paystub and VOE',
 'Fannie Mae B3-3.1-01',
 'docs', 48, 'borrower', null,
 'agency', 'request_documents', 'Employment')

ON CONFLICT (code) DO NOTHING;

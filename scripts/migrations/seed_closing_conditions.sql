-- scripts/migrations/seed_closing_conditions.sql
-- Standard closing conditions. One row per condition type. Includes the
-- data-driven columns (governed_by, recommended_action, review_area) so no
-- backfill is needed. Idempotent via ON CONFLICT (code) DO NOTHING.

INSERT INTO conditions_library (
    code, category, template_text, agency_citation,
    prior_to, sla_hours, assignee, edms_document_type,
    governed_by, recommended_action, review_area
) VALUES

('CLOSING_CD_TIMING',
 'closing',
 'Closing disclosure must be delivered minimum 3 business days before consummation',
 'TRID 12 CFR 1026.19(f) / Reg Z',
 'closing', 24, 'lender', 'CLOSING_DISCLOSURE',
 'federal', 'view_details', 'Closing'),

('CLOSING_RATE_LOCK_EXPIRY',
 'closing',
 'Rate lock expires within 5 days — extend or close before expiration',
 'Fannie Mae B8-1-04',
 'closing', 24, 'lender', null,
 'agency', 'escalate', 'Closing'),

('CLOSING_HOMEOWNERS_INSURANCE',
 'closing',
 'Provide evidence of homeowners insurance binder with lender listed as mortgagee',
 'Fannie Mae B7-3-01',
 'closing', 48, 'borrower', 'HOI_BINDER',
 'agency', 'request_documents', 'Closing'),

('CLOSING_FLOOD_INSURANCE',
 'closing',
 'Property is in SFHA — provide flood insurance policy meeting NFIP requirements',
 'Fannie Mae B7-3-02 / 42 USC §4012a',
 'closing', 48, 'borrower', 'FLOOD_CERT',
 'federal', 'request_documents', 'Closing'),

('CLOSING_TITLE_COMMITMENT',
 'closing',
 'Provide final title commitment showing lender in first lien position',
 'Fannie Mae B8-1-01',
 'closing', 48, 'title', 'TITLE_COMMITMENT',
 'agency', 'view_details', 'Closing'),

('CLOSING_FUNDS_TO_CLOSE',
 'closing',
 'Provide documentation of funds to close — bank statements or wire confirmation',
 'Fannie Mae B3-4.1-01',
 'closing', 24, 'borrower', 'BANK_STATEMENT',
 'agency', 'request_documents', 'Closing'),

('CLOSING_FINAL_VOE',
 'closing',
 'Verbal verification of employment required within 10 days of closing',
 'Fannie Mae B3-3.1-07',
 'closing', 24, 'lender', 'VOE',
 'agency', 'request_documents', 'Closing'),

('CLOSING_PAYOFF_STATEMENT',
 'closing',
 'Provide payoff statement for all liens being satisfied at closing',
 'Fannie Mae B8-1-02',
 'closing', 48, 'borrower', null,
 'agency', 'view_details', 'Closing')

ON CONFLICT (code) DO NOTHING;

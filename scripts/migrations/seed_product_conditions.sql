-- scripts/migrations/seed_product_conditions.sql
-- Standard product conditions. One row per condition type. Includes the
-- data-driven columns (governed_by, recommended_action, review_area) so no
-- backfill is needed. Idempotent via ON CONFLICT (code) DO NOTHING.

INSERT INTO conditions_library (
    code, category, template_text, agency_citation,
    prior_to, sla_hours, assignee, edms_document_type,
    governed_by, recommended_action, review_area
) VALUES

('PRODUCT_VA_ENTITLEMENT',
 'product',
 'Provide Certificate of Eligibility confirming VA entitlement for this loan amount',
 'VA Lenders Handbook Ch 3',
 'docs', 48, 'borrower', 'VA_COE',
 'agency', 'request_documents', 'Underwriting'),

('PRODUCT_VA_FUNDING_FEE',
 'product',
 'VA funding fee must be paid or financed — confirm exemption status if applicable',
 'VA Lenders Handbook Ch 8 / 38 USC §3729',
 'closing', 24, 'lender', null,
 'federal', 'view_details', 'Underwriting'),

('PRODUCT_FHA_MIP',
 'product',
 'FHA mortgage insurance premium calculation must be confirmed before closing',
 'HUD 4000.1 — FHA Single Family Housing Policy Handbook',
 'closing', 24, 'lender', null,
 'agency', 'view_details', 'Underwriting'),

('PRODUCT_CONFORMING_LIMIT',
 'product',
 'Loan amount exceeds conforming limit — verify jumbo eligibility or reduce loan',
 'FHFA Conforming Loan Limits / Fannie Mae B2-1.5-01',
 'docs', 48, 'lender', null,
 'agency', 'escalate', 'Underwriting'),

('PRODUCT_DTI_EXCEPTION',
 'product',
 'DTI exceeds program maximum — compensating factors required for exception approval',
 'Fannie Mae B3-6-02 / 12 CFR 1026.43',
 'docs', 48, 'lender', null,
 'federal', 'escalate', 'Underwriting'),

('PRODUCT_LTV_EXCEPTION',
 'product',
 'LTV exceeds program maximum — verify PMI approval or loan restructure required',
 'Fannie Mae B7-1-02',
 'docs', 48, 'lender', null,
 'agency', 'escalate', 'Underwriting'),

('PRODUCT_AUS_RESUBMIT',
 'product',
 'AUS findings require resubmission with corrected data before underwriting decision',
 'Fannie Mae B3-2-01 / Freddie Mac 5101.1',
 'docs', 48, 'lender', null,
 'agency', 'escalate', 'Underwriting'),

('PRODUCT_INELIGIBLE_BORROWER',
 'product',
 'Borrower eligibility issue identified — senior underwriter review required',
 'Fannie Mae B2-2-01',
 'docs', 48, 'lender', null,
 'agency', 'senior_review', 'Underwriting')

ON CONFLICT (code) DO NOTHING;

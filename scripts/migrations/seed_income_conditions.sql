-- scripts/migrations/seed_income_conditions.sql
-- Standard income conditions. One row per condition type. Includes the
-- data-driven columns (governed_by, recommended_action, review_area) so no
-- backfill is needed. Idempotent via ON CONFLICT (code) DO NOTHING.

INSERT INTO conditions_library (
    code, category, template_text, agency_citation,
    prior_to, sla_hours, assignee, edms_document_type,
    governed_by, recommended_action, review_area
) VALUES

('INCOME_W2_REQUIRED',
 'income',
 'Provide most recent two years W2 statements for all employers',
 'Fannie Mae B3-3.1-01',
 'docs', 48, 'borrower', 'W2',
 'agency', 'request_documents', 'Income'),

('INCOME_PAYSTUB_REQUIRED',
 'income',
 'Provide most recent 30-day paystub showing year-to-date earnings',
 'Fannie Mae B3-3.1-01',
 'docs', 48, 'borrower', 'PAYSTUB',
 'agency', 'request_documents', 'Income'),

('INCOME_TAX_RETURNS_REQUIRED',
 'income',
 'Provide signed federal tax returns for most recent two years',
 'Fannie Mae B3-3.2-01',
 'docs', 48, 'borrower', 'TAX_RETURN',
 'agency', 'request_documents', 'Income'),

('INCOME_SELF_EMPLOYED_CPA',
 'income',
 'Provide CPA-prepared profit and loss statement for current year',
 'Fannie Mae B3-3.4-01',
 'docs', 72, 'borrower', 'PROFIT_LOSS',
 'agency', 'request_documents', 'Income'),

('INCOME_VOE_REQUIRED',
 'income',
 'Provide verbal or written verification of employment from current employer',
 'Fannie Mae B3-3.1-07',
 'closing', 24, 'lender', 'VOE',
 'agency', 'request_documents', 'Income'),

('INCOME_RENTAL_SCHEDULE_E',
 'income',
 'Provide Schedule E from most recent two years tax returns for rental income',
 'Fannie Mae B3-3.1-08',
 'docs', 48, 'borrower', 'SCHEDULE_E',
 'agency', 'request_documents', 'Income'),

('INCOME_DISCREPANCY_EXPLANATION',
 'income',
 'Provide written explanation for income discrepancy between W2 and stated income',
 'Fannie Mae B3-3.1-01 / 12 CFR 1026.43',
 'docs', 48, 'borrower', null,
 'federal', 'request_documents', 'Income'),

('INCOME_GAP_EXPLANATION',
 'income',
 'Provide written explanation for income gap or reduction in current year',
 'Fannie Mae B3-3.1-01',
 'docs', 48, 'borrower', null,
 'agency', 'request_documents', 'Income'),

('INCOME_ALIMONY_DECREE',
 'income',
 'Provide divorce decree or separation agreement documenting alimony or child support income',
 'Fannie Mae B3-3.1-09',
 'docs', 48, 'borrower', 'DIVORCE_DECREE',
 'agency', 'request_documents', 'Income'),

('INCOME_SSA_AWARD_LETTER',
 'income',
 'Provide Social Security award letter dated within 12 months',
 'Fannie Mae B3-3.1-09',
 'docs', 48, 'borrower', 'SSA_AWARD_LETTER',
 'agency', 'request_documents', 'Income')

ON CONFLICT (code) DO NOTHING;

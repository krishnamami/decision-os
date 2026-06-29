-- scripts/migrations/seed_compliance_conditions.sql
-- Standard compliance conditions. One row per condition type. Includes the
-- data-driven columns (governed_by, recommended_action, review_area) so no
-- backfill is needed. Idempotent via ON CONFLICT (code) DO NOTHING.

INSERT INTO conditions_library (
    code, category, template_text, agency_citation,
    prior_to, sla_hours, assignee, edms_document_type,
    governed_by, recommended_action, review_area
) VALUES

('COMPLIANCE_HMDA_COMPLETE',
 'compliance',
 'Complete all required HMDA data fields before loan disposition',
 'HMDA Reg C 12 CFR §1003 / ECOA Reg B',
 'closing', 48, 'lender', null,
 'federal', 'escalate', 'Compliance'),

('COMPLIANCE_FAIR_LENDING_REVIEW',
 'compliance',
 'Fair lending review required — rate or terms deviate from comparable borrower profile',
 'ECOA Reg B 12 CFR §202 / Fair Housing Act',
 'closing', 24, 'lender', null,
 'federal', 'escalate', 'Compliance'),

('COMPLIANCE_TRID_DISCLOSURE',
 'compliance',
 'Loan estimate or closing disclosure requires correction before proceeding',
 'TRID 12 CFR 1026.19 / Reg Z',
 'closing', 24, 'lender', null,
 'federal', 'escalate', 'Compliance'),

('COMPLIANCE_QM_SAFE_HARBOR',
 'compliance',
 'Verify qualified mortgage safe harbor status — DTI or points and fees require review',
 '12 CFR 1026.43(e) / CFPB ATR-QM Rule',
 'closing', 48, 'lender', null,
 'federal', 'escalate', 'Compliance'),

('COMPLIANCE_OFAC_CLEAR',
 'compliance',
 'OFAC watchlist check must be cleared before loan approval',
 'BSA/AML 31 CFR §1010 / OFAC 31 CFR Part 501',
 'docs', 24, 'lender', 'OFAC_REPORT',
 'federal', 'refer_bsa', 'Compliance'),

('COMPLIANCE_STATE_DISCLOSURE',
 'compliance',
 'State-required disclosure must be provided and acknowledged by borrower',
 'State lending law — jurisdiction-specific',
 'docs', 48, 'borrower', null,
 'agency', 'escalate', 'Compliance')

ON CONFLICT (code) DO NOTHING;

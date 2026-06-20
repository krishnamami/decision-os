-- scripts/migrations/seed_title_conditions.sql
-- TL-E — standard title conditions. One row per condition type. Codes align
-- with core/title/lien_resolver.py LIEN_RULES condition_code values (plus the
-- non-lien title conditions the title_assessment persona generates:
-- non-borrower owner, vesting change, missing commitment).

INSERT INTO conditions_library (
    code, category, template_text,
    agency_citation, prior_to, sla_hours,
    assignee, edms_document_type
) VALUES

('TITLE_IRS_LIEN',
 'title',
 'IRS federal tax lien of ${amount} recorded {date} must be satisfied prior to closing. Obtain IRS payoff letter (Form 14135 or lien discharge). Allow 30-45 days for IRS processing. Contact IRS at 1-800-913-6050.',
 'Fannie Mae B2-1.3-04',
 'closing', 72, 'borrower',
 'IRS_PAYOFF_LETTER'),

('TITLE_STATE_TAX_LIEN',
 'title',
 'State tax lien of ${amount} must be paid before closing. Obtain payoff letter from State Revenue Department.',
 'Fannie Mae B2-1.3-04',
 'closing', 48, 'borrower',
 'STATE_TAX_PAYOFF_LETTER'),

('TITLE_PROPERTY_TAX_LIEN',
 'title',
 'Property tax lien must be paid in full at or before closing. Obtain current payoff from County Tax Office.',
 'Fannie Mae B2-1.3-04',
 'closing', 24, 'title',
 'TAX_RECEIPT'),

('TITLE_JUDGMENT_LIEN',
 'title',
 'Judgment lien of ${amount} held by ${holder} must be satisfied before or at closing. Obtain satisfaction of judgment or payoff letter from creditor.',
 'Fannie Mae B2-1.3-04',
 'closing', 48, 'borrower',
 'JUDGMENT_SATISFACTION'),

('TITLE_HOA_LIEN',
 'title',
 'HOA lien of ${amount} owed to ${holder}. Obtain HOA estoppel letter showing current balance due. Amount will be paid at closing from proceeds.',
 'Fannie Mae B2-1.3-04',
 'closing', 48, 'title',
 'HOA_ESTOPPEL_LETTER'),

('TITLE_MECHANICS_LIEN',
 'title',
 'Mechanics lien of ${amount} filed by ${holder}. Obtain lien release or waiver from contractor before closing.',
 'Fannie Mae B2-1.3-04',
 'closing', 72, 'borrower',
 'MECHANICS_LIEN_RELEASE'),

('TITLE_CHILD_SUPPORT_LIEN',
 'title',
 'Child support lien of ${amount} on property. Must be paid or subordinated. Provide court order satisfaction or approved payment plan.',
 'Fannie Mae B2-1.3-04',
 'closing', 48, 'borrower',
 'COURT_ORDER_SATISFACTION'),

('TITLE_LIS_PENDENS',
 'title',
 'Lis pendens (pending lawsuit) recorded on subject property. Closing cannot proceed until lawsuit is resolved. Refer to legal counsel immediately.',
 'Fannie Mae B2-1.3-04',
 'docs', 168, 'lender',
 NULL),

('TITLE_EXISTING_MORTGAGE',
 'title',
 'Existing mortgage held by ${holder} must be paid off at closing. Obtain payoff letter valid through closing date plus 10 days.',
 'Fannie Mae B2-1.3-04',
 'closing', 24, 'title',
 'MORTGAGE_PAYOFF_LETTER'),

('TITLE_HELOC',
 'title',
 'HELOC lien held by ${holder} must be paid off or subordinated. Obtain payoff letter or subordination agreement before closing.',
 'Fannie Mae B2-1.3-04',
 'closing', 48, 'borrower',
 'HELOC_PAYOFF_LETTER'),

('TITLE_NON_BORROWER_OWNER',
 'title',
 '${owner} appears on title but is not on the loan. A quitclaim deed must be executed removing ${owner} from title, OR ${owner} must sign all closing documents as a non-borrowing owner.',
 'Fannie Mae B2-2-01',
 'docs', 72, 'title',
 'QUITCLAIM_DEED'),

('TITLE_VESTING_CHANGE',
 'title',
 'Current vesting (${current_vesting}) differs from loan vesting. Execute deed to correct vesting before or at closing.',
 'Fannie Mae B2-2-01',
 'closing', 48, 'title',
 'VESTING_DEED'),

('TITLE_EASEMENT_REVIEW',
 'title',
 'Easement recorded on property (${easement_type}). Review easement terms to confirm it does not impair intended use or property value. Provide title company confirmation.',
 'Fannie Mae B4-1.3-04',
 'docs', 48, 'title',
 NULL),

('TITLE_COMMITMENT_REQUIRED',
 'title',
 'Title commitment not received. Provide ALTA title commitment from a Fannie Mae approved title insurer before loan can proceed.',
 'Fannie Mae B7-3-01',
 'docs', 48, 'title',
 'TITLE_COMMITMENT'),

('TITLE_OTHER_ENCUMBRANCE',
 'title',
 'Encumbrance found on title. Legal review required. Provide attorney opinion letter addressing encumbrance before closing can proceed.',
 'Fannie Mae B2-1.3-04',
 'docs', 96, 'lender',
 'LEGAL_OPINION_LETTER')

ON CONFLICT (code) DO NOTHING;

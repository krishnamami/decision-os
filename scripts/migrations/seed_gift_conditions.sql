-- scripts/migrations/seed_gift_conditions.sql
-- AV-E — completes the gift-fund chain + bridge-loan exclusion. One row per
-- condition type. Complements the asset conditions seeded in AV-B.

INSERT INTO conditions_library (
    code, category, template_text,
    agency_citation, prior_to, sla_hours,
    assignee, edms_document_type
) VALUES

('ASSET_GIFT_DONOR_BANK_STMT','asset',
 'Provide donor bank statement showing withdrawal of ${amount} from ${donor_name} account within 30 days of gift transfer. Statement must show donor name and account number.',
 'Fannie Mae B3-4.3-04','docs',48,'borrower',
 'GIFT_DONOR_STATEMENT'),

('ASSET_GIFT_NO_REPAYMENT','asset',
 'Gift letter must confirm: (1) donor name and address, (2) relationship to borrower, (3) dollar amount, (4) property address, (5) funds are a gift with NO repayment required.',
 'Fannie Mae B3-4.3-04','docs',48,'borrower',
 'GIFT_LETTER'),

('ASSET_BRIDGE_LOAN_EXCLUDED','asset',
 'Bridge loan proceeds of ${amount} cannot be used for down payment or reserves. Bridge loans are excluded from qualifying assets per Fannie Mae B3-4.3-04.',
 'Fannie Mae B3-4.3-04','docs',24,'lender',NULL)

ON CONFLICT (code) DO NOTHING;

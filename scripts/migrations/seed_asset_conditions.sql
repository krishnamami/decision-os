-- scripts/migrations/seed_asset_conditions.sql
-- AV-B — standard asset conditions. One row per condition type. Codes align
-- with core/assets/asset_resolver.py condition_code values (plus the gift-chain
-- and retirement conditions used by AV-E funds-to-close / gift chain).

INSERT INTO conditions_library (
    code, category, template_text,
    agency_citation, prior_to, sla_hours,
    assignee, edms_document_type
) VALUES

('ASSET_LARGE_DEPOSIT','asset',
 'Large deposit of ${amount} on ${date} in ${institution} account requires documentation: (1) written explanation of source, (2) supporting documents. Per Fannie Mae B3-4.3-04.',
 'Fannie Mae B3-4.3-04','docs',48,'borrower','DEPOSIT_SOURCE_LETTER'),

('ASSET_GIFT_LETTER','asset',
 'Gift funds require: (1) signed gift letter from donor, (2) donor bank statement showing withdrawal, (3) borrower bank statement showing deposit. No repayment clause allowed.',
 'Fannie Mae B3-4.3-04','docs',48,'borrower','GIFT_LETTER'),

('ASSET_GIFT_DONOR_STATEMENT','asset',
 'Provide donor bank statement showing gift withdrawal of ${amount} from ${donor_name} account.',
 'Fannie Mae B3-4.3-04','docs',48,'borrower','GIFT_DONOR_STATEMENT'),

('ASSET_GIFT_TRANSFER_PROOF','asset',
 'Provide evidence of gift transfer: wire confirmation, cashier check, or bank statement showing deposit of ${amount}.',
 'Fannie Mae B3-4.3-04','docs',48,'borrower','GIFT_TRANSFER_PROOF'),

('ASSET_SEASONING','asset',
 '${institution} account has only ${days} days of history (60 required). Provide additional monthly statements or document source of funds.',
 'Fannie Mae B3-4.2-01','docs',48,'borrower','BANK_STATEMENT_ADDITIONAL'),

('ASSET_BUSINESS_CPA','asset',
 'Business account funds require CPA letter confirming withdrawal of ${amount} will not negatively impact business operations.',
 'Fannie Mae B3-4.2-01','docs',72,'borrower','CPA_LETTER'),

('ASSET_RETIREMENT_STATEMENT','asset',
 'Provide most recent retirement account statement showing vested balance. 60% of vested balance used for qualifying assets.',
 'Fannie Mae B3-4.3-04','docs',48,'borrower','RETIREMENT_STATEMENT'),

('ASSET_INSUFFICIENT','asset',
 'Insufficient verified assets for funds to close. Needed: ${funds_needed} (down payment + closing costs + reserves). Available: ${available}. Provide additional asset documentation.',
 'Fannie Mae B3-4.1-01','docs',48,'borrower',NULL)

ON CONFLICT (code) DO NOTHING;

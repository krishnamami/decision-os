-- scripts/migrations/seed_credit_conditions.sql
-- CR-D — standard credit conditions. One row per condition type. Codes align
-- with core/credit/findings_resolver.py (CR-C) and tradeline_analyzer.py (CR-D)
-- condition_code values.

INSERT INTO conditions_library (
    code, category, template_text,
    agency_citation, prior_to, sla_hours,
    assignee, edms_document_type
) VALUES

('CREDIT_LOE_BANKRUPTCY','credit',
 'Provide signed letter of explanation for bankruptcy filed ${date}. Include: cause of bankruptcy, steps taken to reestablish credit, current financial stability.',
 'Fannie Mae B3-5.3-07','docs',48,'borrower','LOE_BANKRUPTCY'),

('CREDIT_LOE_FORECLOSURE','credit',
 'Provide signed letter of explanation for foreclosure completed ${date}. Include: circumstances leading to foreclosure and steps taken since.',
 'Fannie Mae B3-5.3-07','docs',48,'borrower','LOE_FORECLOSURE'),

('CREDIT_LOE_COLLECTION','credit',
 'Provide letter of explanation for collection account: ${creditor} ${amount}. Include current status and resolution plan. Collection must be paid prior to closing if balance exceeds $250.',
 'Fannie Mae B3-5.3-09','docs',48,'borrower','LOE_COLLECTION'),

('CREDIT_LOE_CHARGE_OFF','credit',
 'Provide letter of explanation for charge-off: ${creditor} ${amount}. Include circumstances and current status.',
 'Fannie Mae B3-5.3-09','docs',48,'borrower','LOE_CHARGE_OFF'),

('CREDIT_LOE_MORTGAGE_LATE','credit',
 'Provide letter of explanation for mortgage late payment on ${date}. Include reason for late payment and steps taken to prevent recurrence.',
 'Fannie Mae B3-5.3-07','docs',48,'borrower','LOE_MORTGAGE_LATE'),

('CREDIT_LOE_SHORT_SALE','credit',
 'Provide letter of explanation for short sale completed ${date}. Include circumstances and financial recovery since.',
 'Fannie Mae B3-5.3-07','docs',48,'borrower','LOE_SHORT_SALE'),

('CREDIT_LOE_JUDGMENT','credit',
 'Judgment of ${amount} held by ${creditor} must be paid in full before closing. Provide satisfaction of judgment.',
 'Fannie Mae B3-5.3-09','closing',48,'borrower','JUDGMENT_SATISFACTION'),

('CREDIT_DISPUTED_ACCOUNT','credit',
 'Disputed derogatory account: ${creditor}. Per Fannie Mae B3-5.3-09, dispute notation must be removed before closing. Contact credit bureau to remove dispute.',
 'Fannie Mae B3-5.3-09','closing',72,'borrower','CREDIT_SUPPLEMENT'),

('CREDIT_AUTHORIZED_USER','credit',
 'Authorized user account: ${creditor}. Verify primary account holder is not a related party. Provide documentation confirming arm''s length relationship.',
 'Fannie Mae B3-5.3-09','docs',48,'borrower','AUTHORIZATION_LETTER'),

('CREDIT_STUDENT_DEFERRED','credit',
 'Student loan deferred: ${creditor} balance ${amount}. Per Fannie Mae B3-6-05, DTI calculation uses 1% of balance (${computed_payment}/mo) not the $0 deferred payment.',
 'Fannie Mae B3-6-05','docs',24,'borrower',NULL),

('CREDIT_NONTRADITIONAL','credit',
 'Insufficient traditional credit history (thin file). Provide 12 months of nontraditional credit references: rent payments, utility payments, insurance premiums.',
 'Fannie Mae B3-5.4-01','docs',72,'borrower','NONTRADITIONAL_CREDIT'),

('CREDIT_12MO_CLEAN_HISTORY','credit',
 'Derogatory credit history found. Provide 12 months clean payment history on all accounts since most recent derogatory event.',
 'Fannie Mae B3-5.3-07','docs',48,'borrower',NULL)

ON CONFLICT (code) DO NOTHING;

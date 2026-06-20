-- scripts/migrations/seed_fraud_conditions.sql
-- FR-B — standard fraud conditions. One row per condition type. Codes align
-- with the fraud detectors (FR-B income mismatch; FR-C employment/occupancy;
-- FR-D undisclosed debt) condition_code values.

INSERT INTO conditions_library (
    code, category, template_text,
    agency_citation, prior_to, sla_hours,
    assignee, edms_document_type
) VALUES

('FRAUD_INCOME_MISMATCH','fraud',
 'Income discrepancy detected: URLA states ${urla_amount} but W2 shows ${w2_amount} (${variance}% difference). Provide written explanation for income discrepancy. Additional verification may be required.',
 'Fannie Mae B3-3.1-01','docs',24,'borrower','LOE_INCOME_MISMATCH'),

('FRAUD_EMPLOYER_MISMATCH','fraud',
 'Employer name inconsistency across documents. W2 shows ${w2_employer} but application shows ${urla_employer}. Provide explanation and verification.',
 'Fannie Mae B3-3.1-01','docs',24,'borrower','VOE_WRITTEN'),

('FRAUD_OCCUPANCY_RISK','fraud',
 'Occupancy risk flag: property at ${address} stated as primary residence but indicators suggest investment intent. Provide occupancy certification signed by borrower.',
 'Fannie Mae B2-1.1-01','docs',48,'borrower','OCCUPANCY_CERTIFICATION'),

('FRAUD_UNDISCLOSED_DEBT','fraud',
 'Undisclosed liability found on credit report not listed on application: ${creditor} ${amount}/mo. Provide explanation for omission.',
 'Fannie Mae B3-6-05','docs',24,'borrower','LOE_UNDISCLOSED_DEBT'),

('FRAUD_LARGE_DEPOSIT_PATTERN','fraud',
 'Pattern of large deposits suggests possible fraud: ${deposit_count} deposits totaling ${total_amount} in ${days} days. Source all deposits with documentation.',
 'Fannie Mae B3-4.3-04','docs',48,'borrower','DEPOSIT_SOURCE_LETTER'),

('FRAUD_IDENTITY_REVIEW','fraud',
 'Identity verification required. Provide government-issued photo ID and secondary identification. Identity must be verified before loan can proceed.',
 'BSA/AML Requirements','docs',24,'borrower','DRIVERS_LICENSE')

ON CONFLICT (code) DO NOTHING;

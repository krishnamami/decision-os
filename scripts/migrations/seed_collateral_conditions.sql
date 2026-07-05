-- ============================================================
-- Fix 8 Phase A — seed COLLATERAL_* condition codes into
-- conditions_library (TL-E catalogue). Additive only; no code
-- changes. Adds the citations / SLAs / governed_by / assignees /
-- edms_document_type that the inline collateral builders
-- (core/collateral/appraisal_analyzer.py + property_eligibility_
-- resolver.py) currently omit. Phase B (wiring the builders to
-- query these rows) is deferred.
--
-- Schema note: conditions_library has NO tenant_id / condition_text /
-- blocks_closing — it is a global template catalogue keyed on `code`
-- with `template_text` + `prior_to` (per-loan instances with
-- blocks_closing live in loan_condition_instances). Idempotent on code.
-- ============================================================

INSERT INTO conditions_library
  (code, category, template_text, agency_citation, prior_to, sla_hours,
   assignee, edms_document_type, auto_satisfy, is_active, governed_by,
   recommended_action, review_area, source)
-- NOTE: source='system' and recommended_action='manual_review' from the original
-- draft both violate conditions_library CHECK constraints; corrected to the allowed
-- 'manual' (matches all existing rows) and 'senior_review' for the review-type rows.
SELECT v.code, v.category, v.template_text, v.agency_citation, v.prior_to, v.sla_hours,
       v.assignee, v.edms_document_type, false, true, v.governed_by,
       v.recommended_action, v.review_area, 'manual'
FROM (VALUES
  ('COLLATERAL_APPRAISAL_GAP','property',
   'Appraised value ${appraised_value} is ${gap_amount} below purchase price. Borrower options: cover the gap in cash, renegotiate the purchase price, or exercise the appraisal contingency.',
   'Fannie Mae B4-1.1-01','docs',72,'borrower','APPRAISAL','agency','senior_review','Property'),
  ('COLLATERAL_HIGH_LTV','property',
   'Effective LTV ${ltv}% exceeds the 97% maximum. Additional down payment required to reduce LTV to an eligible level.',
   'Fannie Mae B2-1.2-01','docs',72,'borrower',NULL,'agency','senior_review','Property'),
  ('COLLATERAL_LTV_REVIEW','property',
   'LTV ${ltv}% requires mortgage insurance or an affordable product (HomeReady / Home Possible).',
   'Fannie Mae B7-1-02','docs',48,'lender',NULL,'agency','senior_review','Property'),
  ('COLLATERAL_CONDO_REVIEW','property',
   'Condo project warrantability review required: HOA certification/questionnaire, budget showing under 15% delinquencies, confirmation of no pending litigation, and owner-occupancy above 51%.',
   'Fannie Mae B4-2.1-01','docs',72,'lender','CONDO_QUESTIONNAIRE','agency','request_documents','Property'),
  ('COLLATERAL_MULTIUNIT_RENTS','property',
   'Multi-unit property: provide current leases or a market-rent appraisal (Form 1007/1025) for all units.',
   'Fannie Mae B3-3.1-08','docs',48,'borrower','LEASE','agency','request_documents','Property'),
  ('COLLATERAL_INVESTMENT','property',
   'Investment property: minimum 15% down payment required. Rental income may be used with a two-year history.',
   'Fannie Mae B2-1.2-01','docs',48,'borrower',NULL,'agency','senior_review','Property'),
  ('COLLATERAL_FLOOD_INSURANCE','property',
   'Property in flood zone ${flood_zone}: obtain NFIP or private flood insurance with coverage at least equal to the loan amount before closing.',
   'Fannie Mae B7-3-07','closing',48,'borrower','FLOOD_INSURANCE','federal','request_documents','Property')
) AS v(code, category, template_text, agency_citation, prior_to, sla_hours,
       assignee, edms_document_type, governed_by, recommended_action, review_area)
WHERE NOT EXISTS (SELECT 1 FROM conditions_library l WHERE l.code = v.code);

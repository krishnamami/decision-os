-- Patch unrealistic seed fraud scores for the summit demo tenant.
--
-- The similar-files panel showed values like "Fraud 0.04" for non-fraud loans.
-- Raise the <0.10 cluster (38 loans) to realistic low-risk values in [0.12, 0.35]
-- via a deterministic spread keyed on application_id (reproducible, not random).
--
-- Untouched: the 7 fraud-blocked loans (fraud_score >= 0.75), the 0.10-0.74 band
-- (2 loans at 0.45), and 2 loans with no fraud_score. All patched values stay
-- below the 0.5 persona block threshold, so no fraud outcome changes.
--
-- fraud_score lives in entity_states.borrower->'identity'->>'fraud_score'.
-- Run as edms_admin.

UPDATE entity_states
SET borrower = jsonb_set(
      borrower,
      '{identity,fraud_score}',
      to_jsonb(round((0.12 + (abs(hashtext(application_id)) % 24)::numeric / 100.0), 2))
    )
WHERE tenant_id = 'summit'
  AND (borrower->'identity'->>'fraud_score') IS NOT NULL
  AND (borrower->'identity'->>'fraud_score')::float < 0.10;

-- Expected: UPDATE 38. Verify band breakdown:
--   <0.10 -> 0, 0.10-0.74 -> 40, >=0.75 -> 7, NULL -> 2  (total 49)

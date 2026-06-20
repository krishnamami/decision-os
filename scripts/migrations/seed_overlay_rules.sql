-- ============================================================
-- seed_overlay_rules
-- ------------------------------------------------------------
-- Lender overlay rules for existing tenants. overlay_rules is
-- Layer 2 of ThresholdResolver.resolve_credit_floor() — it sits
-- ABOVE tenant_rules.rules JSONB and BELOW tenant waivers. With
-- the table empty the resolver always fell through to tenant_rules
-- / the agency floor; these overlays make the lender's documented
-- stricter-than-agency requirements active.
--
-- Every value here has been checked against platform_guardrails
-- (P0-B) — overlays may only tighten: credit floors go UP, DTI/LTV
-- caps go DOWN, never past the platform ceiling / agency floor.
--
-- loan_type is stored lowercase to match the value the resolver's
-- overlay query compares against (loan_type = $2).
-- Idempotent: re-running inserts nothing already present.
-- ============================================================

INSERT INTO overlay_rules
    (tenant_id, rule_type, loan_type, overlay_value, direction, is_active)
SELECT v.tenant_id, v.rule_type, v.loan_type,
       v.overlay_value::numeric, v.direction, v.is_active
FROM (VALUES
    -- Meridian — conventional (stricter than Fannie)
    ('meridian', 'credit_floor',     'conventional', 660, 'stricter', true),
    ('meridian', 'dti_back_max',     'conventional', 43,  'stricter', true),
    ('meridian', 'ltv_max_purchase', 'conventional', 95,  'stricter', true),
    -- Meridian — fha
    ('meridian', 'dti_back_max',     'fha',          50,  'stricter', true),
    -- Summit — conventional
    ('summit',   'credit_floor',     'conventional', 680, 'stricter', true),
    ('summit',   'dti_back_max',     'conventional', 43,  'stricter', true)
) AS v(tenant_id, rule_type, loan_type, overlay_value, direction, is_active)
WHERE NOT EXISTS (
    SELECT 1 FROM overlay_rules o
    WHERE o.tenant_id = v.tenant_id
      AND o.rule_type = v.rule_type
      AND o.loan_type IS NOT DISTINCT FROM v.loan_type
);

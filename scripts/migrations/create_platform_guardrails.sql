-- ============================================================
-- platform_guardrails
-- ------------------------------------------------------------
-- Outer boundaries a tenant overlay may never exceed. Two-sided:
--   agency_floor      — the lowest a value may go (credit scores).
--                       A tenant may require HIGHER, never lower.
--   platform_ceiling  — the highest a value may go (DTI / LTV).
--                       A tenant may set LOWER, never higher.
-- Tenant overlay_rules / tenant_rules must resolve to a value
-- between these bounds. ThresholdResolver.validate_overlay_within_bounds()
-- enforces this before an overlay is saved.
-- ============================================================

CREATE TABLE IF NOT EXISTS platform_guardrails (
    id               UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    product_type     VARCHAR(50)  NOT NULL,
    parameter        VARCHAR(100) NOT NULL,
    agency_floor     NUMERIC,
    platform_ceiling NUMERIC,
    description      TEXT,
    effective_date   DATE        DEFAULT CURRENT_DATE,
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (product_type, parameter)
);

-- Seed the outer limits Accord enforces. Tenants cannot configure
-- overlay rules outside these bounds.
INSERT INTO platform_guardrails
    (product_type, parameter, agency_floor, platform_ceiling, description)
VALUES
-- CONVENTIONAL
('conventional', 'credit_floor',     620, 850,
 'Fannie/Freddie minimum 620. Tenant can require higher but not lower.'),
('conventional', 'dti_back_max',     NULL, 50,
 'Fannie max 50%. Tenant can set lower but not higher.'),
('conventional', 'ltv_max_purchase', NULL, 97,
 'Fannie max 97%. Tenant can set lower but not higher.'),
('conventional', 'ltv_max_cashout',  NULL, 80,
 'Fannie max 80% cash-out. Tenant cannot exceed.'),
('conventional', 'ltv_max_refi',     NULL, 95,
 'Fannie max 95% rate/term refi. Tenant cannot exceed.'),

-- FHA
('fha', 'credit_floor',     500, 850,
 'FHA absolute minimum 500. 580+ for 96.5% LTV.'),
('fha', 'dti_back_max',     NULL, 57,
 'FHA max 57% with AUS approval. Tenant cannot exceed.'),
('fha', 'ltv_max_purchase', NULL, 96.5,
 'FHA max 96.5% (580+ credit). 90% max for 500-579.'),

-- VA
('va', 'credit_floor',     NULL, NULL,
 'VA has no agency floor. Tenant sets minimum.'),
('va', 'dti_back_max',     NULL, 65,
 'VA guideline 41% but allows higher with residual income. Platform cap 65%.'),
('va', 'ltv_max_purchase', NULL, 100,
 'VA allows 100% LTV with full entitlement.'),

-- USDA
('usda', 'credit_floor', 640, 850,
 'USDA minimum 640 for GUS automated. Tenant cannot go lower.'),
('usda', 'dti_back_max', NULL, 41,
 'USDA max 41% without exception.'),

-- JUMBO (platform-defined, no agency)
('jumbo', 'credit_floor', 680, 850,
 'Platform minimum for jumbo. No agency floor.'),
('jumbo', 'dti_back_max', NULL, 43,
 'Platform maximum for jumbo. No agency floor.')

ON CONFLICT (product_type, parameter) DO NOTHING;

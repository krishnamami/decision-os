-- Accord Rules Dashboard — the three-layer trust foundation.
--   regulatory_rules   🔒 federal & state law (Accord-maintained, locked)
--   agency_guidelines  📋 Fannie/Freddie/FHA/VA/USDA (preset, monitored)
--   tenant_rules       🔧 per-tenant risk-appetite overlays (versioned, adjustable)
-- Plus data-freshness tracking and agency/regulatory change alerts.
-- Idempotent and additive — safe to re-run.

-- ── Layer 1: Federal & state regulatory rules (locked) ──────────────
CREATE TABLE IF NOT EXISTS regulatory_rules (
  rule_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  authority VARCHAR NOT NULL,       -- federal, state, ofac, qm, cfpb, bsa
  state_code VARCHAR,               -- NULL for federal, 'TX'/'CA'/'NY' for state
  category VARCHAR NOT NULL,        -- credit, dti, ltv, fraud, disclosure, timeline
  rule_name VARCHAR NOT NULL,
  rule_value JSONB NOT NULL,        -- { "type": "threshold", "value": 43, "operator": "max" }
  display_value VARCHAR,            -- "43%" for UI display
  description TEXT NOT NULL,
  citation TEXT,                    -- "12 CFR 1026.43(e)(2)" or "TX Const. Art XVI §50"
  source_url VARCHAR,               -- link to original law/regulation
  effective_date DATE,
  is_active BOOLEAN DEFAULT true,
  updated_at TIMESTAMP DEFAULT NOW()
);

-- ── Layer 2: Agency guidelines (preset, monitored) ──────────────────
CREATE TABLE IF NOT EXISTS agency_guidelines (
  guideline_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  agency VARCHAR NOT NULL,          -- fannie, freddie, fha, va, usda
  category VARCHAR NOT NULL,        -- credit, dti, ltv, reserves, income, property, mi
  guideline_name VARCHAR NOT NULL,
  guideline_value JSONB NOT NULL,
  display_value VARCHAR,
  description TEXT NOT NULL,
  conditions TEXT,                  -- "With DU Approve/Eligible and compensating factors"
  citation TEXT,                    -- "Selling Guide B3-6-02"
  source_url VARCHAR,
  effective_date DATE,
  last_verified DATE,
  verified_by VARCHAR,              -- "Accord compliance team" or "External counsel"
  is_active BOOLEAN DEFAULT true,
  updated_at TIMESTAMP DEFAULT NOW()
);

-- ── Layer 3: Customer overlay rules (per-tenant, versioned) ─────────
CREATE TABLE IF NOT EXISTS tenant_rules (
  rule_version_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id VARCHAR NOT NULL REFERENCES tenants(tenant_id),
  version INT NOT NULL,
  status VARCHAR NOT NULL DEFAULT 'draft',
    -- draft, pending_approval, active, superseded
  rules JSONB NOT NULL,
  programs JSONB DEFAULT '["conventional","fha"]',
  changes_summary TEXT,
  change_reason TEXT,
  created_by UUID REFERENCES users(user_id),
  approved_by UUID REFERENCES users(user_id),
  effective_from TIMESTAMP,
  effective_to TIMESTAMP,
  created_at TIMESTAMP DEFAULT NOW(),
  approved_at TIMESTAMP
);

-- ── Data freshness tracking ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS data_source_status (
  source_id VARCHAR PRIMARY KEY,    -- ofac_sdn, conforming_limits, fha_limits, etc.
  source_name VARCHAR NOT NULL,
  source_url VARCHAR,
  last_download TIMESTAMP,
  last_success TIMESTAMP,
  record_count INT,
  status VARCHAR DEFAULT 'ok',      -- ok, stale, error
  next_scheduled TIMESTAMP,
  error_message TEXT,
  updated_at TIMESTAMP DEFAULT NOW()
);

-- ── Rule change alerts (monitoring agency/regulatory changes) ───────
CREATE TABLE IF NOT EXISTS rule_change_alerts (
  alert_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source VARCHAR NOT NULL,          -- fannie_sel, freddie_bulletin, hud_ml, fhfa
  title TEXT NOT NULL,
  description TEXT,
  url VARCHAR,
  published_date DATE,
  status VARCHAR DEFAULT 'new',     -- new, reviewing, applied, dismissed
  reviewed_by UUID,
  reviewed_at TIMESTAMP,
  created_at TIMESTAMP DEFAULT NOW()
);

-- Track which rule version was used for each decision.
ALTER TABLE decision_outputs ADD COLUMN IF NOT EXISTS rule_version_id UUID;

CREATE INDEX IF NOT EXISTS idx_regulatory_category ON regulatory_rules(category, is_active);
CREATE INDEX IF NOT EXISTS idx_agency_category ON agency_guidelines(agency, category, is_active);
CREATE INDEX IF NOT EXISTS idx_tenant_rules_active ON tenant_rules(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_data_source ON data_source_status(status);

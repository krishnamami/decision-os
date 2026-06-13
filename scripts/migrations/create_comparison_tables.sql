-- Accord Comparison Mode — run Accord alongside manual underwriting for a
-- trial period and track agreement. Additive + idempotent.

CREATE TABLE IF NOT EXISTS comparison_decisions (
  comparison_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  application_id VARCHAR NOT NULL,
  tenant_id VARCHAR NOT NULL,

  -- Accord's decision
  accord_outcome VARCHAR,          -- allow, block, review, escalate
  accord_confidence FLOAT,
  accord_reasoning TEXT,
  accord_decided_at TIMESTAMP,

  -- Manual underwriter's decision
  manual_outcome VARCHAR,          -- approved, denied, suspended, withdrawn
  manual_decided_by UUID,
  manual_reasoning TEXT,
  manual_decided_at TIMESTAMP,

  -- Comparison result
  agreement VARCHAR,               -- agree, accord_stricter, accord_looser, disagree
  agreement_details TEXT,
  resolution TEXT,                 -- which decision was ultimately correct

  -- Performance tracking (filled in over time)
  loan_performance VARCHAR,        -- performing, delinquent_30/60/90, default, paid_off
  performance_updated_at TIMESTAMP,

  created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS comparison_periods (
  period_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id VARCHAR NOT NULL,
  started_at TIMESTAMP DEFAULT NOW(),
  started_by UUID,
  ends_at TIMESTAMP,               -- typically 90 days from start
  status VARCHAR DEFAULT 'active', -- active, completed, cancelled
  total_loans INT DEFAULT 0,
  agreement_rate FLOAT,
  completed_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_comparison_tenant ON comparison_decisions(tenant_id);
CREATE INDEX IF NOT EXISTS idx_comparison_agreement ON comparison_decisions(tenant_id, agreement);
CREATE INDEX IF NOT EXISTS idx_comparison_period ON comparison_periods(tenant_id, status);

-- Accord auth & multi-tenancy schema.
-- Run with: python scripts/migrations/run_auth_migration.py
--   (the runner bcrypt-hashes 'accord2026' in place of HASH_IN_CODE, and
--    only executes the @RETENANT block when passed --retenant)
--
-- NOTE: a `tenants` table already exists in EDMS PG with a smaller schema
-- (tenant_id, name, is_active, created_at). CREATE TABLE IF NOT EXISTS is
-- therefore a no-op on that DB, so the ALTERs below add the new columns.

-- ── tenants ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tenants (
  tenant_id  VARCHAR(50) PRIMARY KEY,
  name       VARCHAR(255) NOT NULL,
  plan       VARCHAR(20) NOT NULL DEFAULT 'starter'
             CHECK (plan IN ('starter', 'growth', 'business', 'enterprise')),
  products   JSONB NOT NULL DEFAULT '["pipeline"]',
  settings   JSONB DEFAULT '{}',
  logo_url   VARCHAR(500),
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);

-- Bring a pre-existing tenants table up to the full schema.
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS plan       VARCHAR(20) NOT NULL DEFAULT 'starter';
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS products   JSONB NOT NULL DEFAULT '["pipeline"]';
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS settings   JSONB DEFAULT '{}';
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS logo_url   VARCHAR(500);
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW();

-- Add the plan CHECK constraint if the table pre-existed without it.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'tenants_plan_check') THEN
    ALTER TABLE tenants ADD CONSTRAINT tenants_plan_check
      CHECK (plan IN ('starter', 'growth', 'business', 'enterprise'));
  END IF;
END $$;

-- ── users ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
  user_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     VARCHAR(50) NOT NULL REFERENCES tenants(tenant_id),
  email         VARCHAR(255) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  name          VARCHAR(255) NOT NULL,
  role          VARCHAR(20) NOT NULL DEFAULT 'underwriter'
                CHECK (role IN ('admin', 'manager', 'underwriter', 'compliance', 'viewer')),
  is_active     BOOLEAN DEFAULT true,
  last_login    TIMESTAMP,
  created_at    TIMESTAMP DEFAULT NOW(),
  updated_at    TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_tenant ON users(tenant_id);
CREATE INDEX IF NOT EXISTS idx_users_email  ON users(email);

-- ── seed: demo tenant + admin/uw/compliance/viewer users ─────────────
INSERT INTO tenants (tenant_id, name, plan, products) VALUES
  ('demo', 'Demo Lender', 'enterprise',
   '["pipeline", "analytics", "simulation", "audit"]')
ON CONFLICT (tenant_id) DO NOTHING;

-- password "accord2026" — HASH_IN_CODE is replaced with a bcrypt hash by the runner.
INSERT INTO users (tenant_id, email, password_hash, name, role) VALUES
  ('demo', 'admin@demo.com',      'HASH_IN_CODE', 'Krishna Mami',       'admin'),
  ('demo', 'uw@demo.com',         'HASH_IN_CODE', 'Sarah Underwriter',  'underwriter'),
  ('demo', 'compliance@demo.com', 'HASH_IN_CODE', 'Tom Compliance',     'compliance'),
  ('demo', 'viewer@demo.com',     'HASH_IN_CODE', 'Jane Viewer',        'viewer')
ON CONFLICT (email) DO NOTHING;

-- @RETENANT_START
-- DESTRUCTIVE: moves all existing data from tenant 'default' to 'demo'.
-- The Accord API currently defaults every query to tenant_id='default', so
-- after this the app shows ZERO data unless the API default is also changed
-- to 'demo' (or the auth layer supplies the tenant). Only run deliberately:
--   python scripts/migrations/run_auth_migration.py --retenant
UPDATE entity_states       SET tenant_id = 'demo' WHERE tenant_id = 'default';
UPDATE decision_outputs    SET tenant_id = 'demo' WHERE tenant_id = 'default';
UPDATE mirofish_debates    SET tenant_id = 'demo' WHERE tenant_id = 'default';
UPDATE mirofish_simulations SET tenant_id = 'demo' WHERE tenant_id = 'default';
UPDATE mirofish_swarm_runs  SET tenant_id = 'demo' WHERE tenant_id = 'default';
-- @RETENANT_END

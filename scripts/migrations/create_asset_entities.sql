-- scripts/migrations/create_asset_entities.sql
-- AV-A — asset entity model. Schema only (same pattern as TL-A / CR-A). The
-- current asset pipeline carries a bank-statement balance + a large-deposit
-- flag; these tables add asset classification, seasoning, gift tracking,
-- retirement/stock qualifying factors, business-asset treatment, and
-- per-deposit sourcing.

-- ─────────────────────────────────────────────
-- ASSET_ACCOUNTS
-- One row per account across all asset types.
-- Populated from bank statements, investment
-- statements, retirement statements.
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS asset_accounts (
    id               UUID DEFAULT gen_random_uuid()
                     PRIMARY KEY,
    application_id   VARCHAR(50) NOT NULL,
    tenant_id        VARCHAR(50) NOT NULL,

    -- Account identity
    institution_name VARCHAR(200),
    account_type     VARCHAR(50) NOT NULL
                     CHECK (account_type IN (
                         'checking',
                         'savings',
                         'money_market',
                         'cd',
                         'brokerage',
                         'stocks_bonds',
                         'ira',
                         '401k',
                         '403b',
                         'pension',
                         'annuity',
                         'business_account',
                         'crypto',
                         'gift_funds',
                         'proceeds_sale',
                         'bridge_loan',
                         'other'
                     )),
    account_number_last4 VARCHAR(4),

    -- Balances
    current_balance  NUMERIC NOT NULL,
    vested_balance   NUMERIC,
    statement_date   DATE,
    statement_month  INTEGER,

    -- Qualifying factors
    qualifying_factor NUMERIC DEFAULT 1.0
                      CHECK (qualifying_factor
                             BETWEEN 0 AND 1),
    qualifying_amount NUMERIC,
    seasoned_days    INTEGER,
    is_seasoned      BOOLEAN DEFAULT TRUE,

    -- Flags
    is_gift          BOOLEAN DEFAULT FALSE,
    gift_documented  BOOLEAN DEFAULT FALSE,
    is_business      BOOLEAN DEFAULT FALSE,
    business_ownership_pct NUMERIC,
    is_crypto        BOOLEAN DEFAULT FALSE,
    crypto_excluded  BOOLEAN DEFAULT FALSE,

    -- Large deposits
    has_large_deposit BOOLEAN DEFAULT FALSE,
    large_deposit_amount NUMERIC,
    large_deposit_sourced BOOLEAN DEFAULT FALSE,
    large_deposit_date DATE,

    source_document_id VARCHAR(100),
    notes            TEXT,
    created_at       TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS
    idx_asset_accounts_app
    ON asset_accounts(application_id, tenant_id);

CREATE INDEX IF NOT EXISTS
    idx_asset_accounts_type
    ON asset_accounts(application_id, account_type);


-- ─────────────────────────────────────────────
-- ASSET_DEPOSITS
-- Individual large deposits requiring sourcing.
-- One row per deposit that exceeds threshold.
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS asset_deposits (
    id               UUID DEFAULT gen_random_uuid()
                     PRIMARY KEY,
    application_id   VARCHAR(50) NOT NULL,
    tenant_id        VARCHAR(50) NOT NULL,
    account_id       UUID REFERENCES
                         asset_accounts(id)
                         ON DELETE CASCADE,

    deposit_date     DATE,
    deposit_amount   NUMERIC NOT NULL,
    deposit_source   VARCHAR(100),
    is_sourced       BOOLEAN DEFAULT FALSE,
    source_document_id VARCHAR(100),
    is_gift          BOOLEAN DEFAULT FALSE,
    gift_letter_received BOOLEAN DEFAULT FALSE,

    -- Threshold check
    threshold_used   NUMERIC,
    exceeds_threshold BOOLEAN DEFAULT TRUE,
    notes            TEXT,
    created_at       TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS
    idx_deposits_app
    ON asset_deposits(application_id, tenant_id);

CREATE INDEX IF NOT EXISTS
    idx_deposits_unsourced
    ON asset_deposits(application_id, is_sourced)
    WHERE is_sourced = FALSE;


-- RLS
ALTER TABLE asset_accounts
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE asset_deposits
    ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
  DROP POLICY IF EXISTS aa_read ON asset_accounts;
  CREATE POLICY aa_read ON asset_accounts
      FOR SELECT USING (
          tenant_id = current_setting(
              'app.tenant_id', true
          ) OR current_user = 'edms_admin'
      );
  DROP POLICY IF EXISTS aa_write ON asset_accounts;
  CREATE POLICY aa_write ON asset_accounts
      FOR INSERT WITH CHECK (true);

  DROP POLICY IF EXISTS ad_read ON asset_deposits;
  CREATE POLICY ad_read ON asset_deposits
      FOR SELECT USING (
          tenant_id = current_setting(
              'app.tenant_id', true
          ) OR current_user = 'edms_admin'
      );
  DROP POLICY IF EXISTS ad_write ON asset_deposits;
  CREATE POLICY ad_write ON asset_deposits
      FOR INSERT WITH CHECK (true);
END $$;

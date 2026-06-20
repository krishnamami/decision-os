-- scripts/migrations/create_credit_entities.sql
-- CR-A — credit tradeline + findings entity model. Schema only (same pattern
-- as TL-A title entities). The current credit pipeline carries one score + one
-- obligation total; these tables add individual tradelines and derogatory
-- findings (collections, charge-offs, bankruptcies, disputed accounts).

-- ─────────────────────────────────────────────
-- CREDIT_TRADELINES
-- One row per tradeline from credit report.
-- Feeds: obligation resolver, credit findings.
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS credit_tradelines (
    id               UUID DEFAULT gen_random_uuid()
                     PRIMARY KEY,
    application_id   VARCHAR(50) NOT NULL,
    tenant_id        VARCHAR(50) NOT NULL,

    -- Account info
    creditor_name    VARCHAR(200),
    account_type     VARCHAR(50)
                     CHECK (account_type IN (
                         'mortgage',
                         'heloc',
                         'auto_loan',
                         'credit_card',
                         'student_loan',
                         'personal_loan',
                         'medical',
                         'collection',
                         'charge_off',
                         'installment',
                         'revolving',
                         'other'
                     )),
    account_number_last4 VARCHAR(4),
    open_date        DATE,
    closed_date      DATE,
    is_open          BOOLEAN DEFAULT TRUE,

    -- Balances
    credit_limit     NUMERIC,
    high_balance     NUMERIC,
    current_balance  NUMERIC,
    monthly_payment  NUMERIC,
    months_remaining INTEGER,

    -- Payment history
    payment_status   VARCHAR(20)
                     CHECK (payment_status IN (
                         'current',
                         'late_30',
                         'late_60',
                         'late_90',
                         'late_120',
                         'collection',
                         'charge_off',
                         'foreclosure',
                         'bankruptcy',
                         'paid',
                         'unknown'
                     )),
    late_30_count    INTEGER DEFAULT 0,
    late_60_count    INTEGER DEFAULT 0,
    late_90_count    INTEGER DEFAULT 0,
    last_late_date   DATE,

    -- Flags
    is_authorized_user  BOOLEAN DEFAULT FALSE,
    is_disputed         BOOLEAN DEFAULT FALSE,
    is_medical          BOOLEAN DEFAULT FALSE,
    exclude_from_dti    BOOLEAN DEFAULT FALSE,
    exclusion_reason    VARCHAR(100),

    -- Student loan specific
    student_loan_type   VARCHAR(20)
                        CHECK (student_loan_type IN (
                            'standard',
                            'ibr',
                            'paye',
                            'save',
                            'deferred',
                            'pslf',
                            'parent_plus'
                        )),
    ibr_payment         NUMERIC,

    source_document_id  VARCHAR(100),
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS
    idx_tradelines_app
    ON credit_tradelines(
        application_id, tenant_id
    );

CREATE INDEX IF NOT EXISTS
    idx_tradelines_derogatory
    ON credit_tradelines(
        application_id, payment_status
    )
    WHERE payment_status NOT IN (
        'current', 'paid', 'unknown'
    );


-- ─────────────────────────────────────────────
-- CREDIT_FINDINGS
-- Summary findings from tradeline analysis.
-- One row per finding type.
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS credit_findings (
    id               UUID DEFAULT gen_random_uuid()
                     PRIMARY KEY,
    application_id   VARCHAR(50) NOT NULL,
    tenant_id        VARCHAR(50) NOT NULL,

    finding_type     VARCHAR(50) NOT NULL
                     CHECK (finding_type IN (
                         'bankruptcy_ch7',
                         'bankruptcy_ch13',
                         'foreclosure',
                         'short_sale',
                         'deed_in_lieu',
                         'collection_medical',
                         'collection_non_medical',
                         'charge_off',
                         'judgment',
                         'tax_lien_credit',
                         'mortgage_late_12mo',
                         'mortgage_late_24mo',
                         'thin_file',
                         'authorized_user_only',
                         'disputed_account',
                         'inquiry_recent'
                     )),

    severity         VARCHAR(20) NOT NULL
                     CHECK (severity IN (
                         'informational',
                         'minor',
                         'moderate',
                         'major',
                         'fatal'
                     )),

    -- Finding details
    event_date       DATE,
    discharge_date   DATE,
    amount           NUMERIC,
    creditor_name    VARCHAR(200),
    description      TEXT,

    -- Agency waiting periods
    fannie_wait_years  NUMERIC,
    fha_wait_years     NUMERIC,
    va_wait_years      NUMERIC,
    eligible_date      DATE,
    currently_eligible BOOLEAN DEFAULT TRUE,

    -- Resolution
    blocks_approval  BOOLEAN DEFAULT FALSE,
    requires_loe     BOOLEAN DEFAULT FALSE,
    loe_condition_code VARCHAR(100),

    source_document_id VARCHAR(100),
    created_at       TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS
    idx_credit_findings_app
    ON credit_findings(
        application_id, tenant_id
    );

CREATE INDEX IF NOT EXISTS
    idx_credit_findings_blocking
    ON credit_findings(
        application_id, blocks_approval
    )
    WHERE blocks_approval = TRUE;


-- RLS
ALTER TABLE credit_tradelines
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE credit_findings
    ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
  DROP POLICY IF EXISTS ct_read
      ON credit_tradelines;
  CREATE POLICY ct_read
      ON credit_tradelines FOR SELECT
      USING (
          tenant_id = current_setting(
              'app.tenant_id', true
          )
          OR current_user = 'edms_admin'
      );
  DROP POLICY IF EXISTS ct_write
      ON credit_tradelines;
  CREATE POLICY ct_write
      ON credit_tradelines FOR INSERT
      WITH CHECK (true);

  DROP POLICY IF EXISTS cf_read
      ON credit_findings;
  CREATE POLICY cf_read
      ON credit_findings FOR SELECT
      USING (
          tenant_id = current_setting(
              'app.tenant_id', true
          )
          OR current_user = 'edms_admin'
      );
  DROP POLICY IF EXISTS cf_write
      ON credit_findings;
  CREATE POLICY cf_write
      ON credit_findings FOR INSERT
      WITH CHECK (true);
END $$;

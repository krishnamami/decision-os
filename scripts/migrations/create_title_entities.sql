-- ============================================================
-- Title entity model (TL-A). Schema only; no persona changes.
--   property_encumbrances : one row per lien/encumbrance
--   title_findings        : one row per title-search finding
--   ownership_chain       : vesting / ownership details
-- Foundation for TL-B (extractor), TL-C (lien resolver),
-- TL-D (title_assessment persona).
-- ============================================================

-- ─────────────────────────────────────────────
-- PROPERTY_ENCUMBRANCES — one row per lien/encumbrance,
-- populated from the title commitment Schedule B.
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS property_encumbrances (
    id                 UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    application_id     VARCHAR(50) NOT NULL,
    tenant_id          VARCHAR(50) NOT NULL,
    property_address   TEXT,
    lien_type          VARCHAR(50) NOT NULL
                       CHECK (lien_type IN (
                           'tax_lien_irs', 'tax_lien_state', 'tax_lien_property',
                           'judgment_lien', 'hoa_lien', 'mechanics_lien',
                           'child_support_lien', 'mortgage_lien', 'heloc_lien',
                           'easement', 'restriction_cc_r', 'lis_pendens', 'other')),
    lien_holder        VARCHAR(200),
    lien_amount        NUMERIC,
    recorded_date      DATE,
    instrument_number  VARCHAR(100),
    priority           INTEGER,
    resolvable         BOOLEAN DEFAULT TRUE,
    resolution_method  VARCHAR(100)
                       CHECK (resolution_method IN (
                           'pay_at_closing', 'subordination', 'release_required',
                           'payoff_letter', 'legal_review', 'cannot_clear',
                           'already_released')),
    estimated_payoff   NUMERIC,
    blocks_closing     BOOLEAN DEFAULT FALSE,
    source_document_id VARCHAR(100),
    notes              TEXT,
    created_at         TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT fk_encumbrance_doc
        FOREIGN KEY (source_document_id) REFERENCES document_index(document_id)
        ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED
);

CREATE INDEX IF NOT EXISTS idx_encumbrances_app
    ON property_encumbrances(application_id, tenant_id);
CREATE INDEX IF NOT EXISTS idx_encumbrances_type
    ON property_encumbrances(application_id, lien_type);
CREATE INDEX IF NOT EXISTS idx_encumbrances_blocking
    ON property_encumbrances(application_id, blocks_closing)
    WHERE blocks_closing = TRUE;


-- ─────────────────────────────────────────────
-- TITLE_FINDINGS — summary findings from the title search.
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS title_findings (
    id                 UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    application_id     VARCHAR(50) NOT NULL,
    tenant_id          VARCHAR(50) NOT NULL,
    finding_type       VARCHAR(50) NOT NULL
                       CHECK (finding_type IN (
                           'clear', 'lien_found', 'ownership_dispute', 'vesting_error',
                           'missing_signature', 'survey_issue', 'easement_conflict',
                           'legal_description_error', 'prior_deed_defect',
                           'probate_required', 'bankruptcy_estate',
                           'foreclosure_action', 'other')),
    severity           VARCHAR(20) NOT NULL
                       CHECK (severity IN ('clear', 'minor', 'moderate', 'major', 'fatal')),
    description        TEXT,
    resolvable         BOOLEAN DEFAULT TRUE,
    resolution_steps   TEXT,
    estimated_days     INTEGER,
    blocks_closing     BOOLEAN DEFAULT FALSE,
    source_document_id VARCHAR(100),
    created_at         TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_title_findings_app
    ON title_findings(application_id, tenant_id);
CREATE INDEX IF NOT EXISTS idx_title_findings_severity
    ON title_findings(application_id, severity)
    WHERE severity IN ('major', 'fatal');


-- ─────────────────────────────────────────────
-- OWNERSHIP_CHAIN — vesting and ownership details.
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ownership_chain (
    id                 UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    application_id     VARCHAR(50) NOT NULL,
    tenant_id          VARCHAR(50) NOT NULL,
    owner_name         VARCHAR(200),
    ownership_pct      NUMERIC CHECK (ownership_pct >= 0 AND ownership_pct <= 100),
    vesting_type       VARCHAR(50)
                       CHECK (vesting_type IN (
                           'sole_and_separate', 'joint_tenancy', 'tenants_in_common',
                           'community_property', 'trust', 'llc', 'corporation', 'unknown')),
    is_borrower        BOOLEAN DEFAULT FALSE,
    on_loan            BOOLEAN DEFAULT FALSE,
    must_sign_docs     BOOLEAN DEFAULT TRUE,
    notes              TEXT,
    source_document_id VARCHAR(100),
    created_at         TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ownership_app
    ON ownership_chain(application_id, tenant_id);


-- ─────────────────────────────────────────────
-- RLS on all title tables (tenant read scoping + edms_admin).
-- ─────────────────────────────────────────────
ALTER TABLE property_encumbrances ENABLE ROW LEVEL SECURITY;
ALTER TABLE title_findings        ENABLE ROW LEVEL SECURITY;
ALTER TABLE ownership_chain       ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
  DROP POLICY IF EXISTS pe_read ON property_encumbrances;
  CREATE POLICY pe_read ON property_encumbrances FOR SELECT
      USING (tenant_id = current_setting('app.tenant_id', true) OR current_user = 'edms_admin');
  DROP POLICY IF EXISTS pe_write ON property_encumbrances;
  CREATE POLICY pe_write ON property_encumbrances FOR INSERT WITH CHECK (true);

  DROP POLICY IF EXISTS tf_read ON title_findings;
  CREATE POLICY tf_read ON title_findings FOR SELECT
      USING (tenant_id = current_setting('app.tenant_id', true) OR current_user = 'edms_admin');
  DROP POLICY IF EXISTS tf_write ON title_findings;
  CREATE POLICY tf_write ON title_findings FOR INSERT WITH CHECK (true);

  DROP POLICY IF EXISTS oc_read ON ownership_chain;
  CREATE POLICY oc_read ON ownership_chain FOR SELECT
      USING (tenant_id = current_setting('app.tenant_id', true) OR current_user = 'edms_admin');
  DROP POLICY IF EXISTS oc_write ON ownership_chain;
  CREATE POLICY oc_write ON ownership_chain FOR INSERT WITH CHECK (true);
END $$;

-- scripts/migrations/create_property_eligibility.sql
-- CO-A — per-application property eligibility record (schema + resolver, same
-- pattern as TL-A). The current collateral pipeline carries appraised_value /
-- LTV / property_type; this adds eligibility per agency, ineligible types,
-- condo warrantability, flood zone, and special conditions.

CREATE TABLE IF NOT EXISTS property_eligibility (
    id               UUID DEFAULT gen_random_uuid()
                     PRIMARY KEY,
    application_id   VARCHAR(50) NOT NULL,
    tenant_id        VARCHAR(50) NOT NULL,

    -- Property classification
    property_type    VARCHAR(50)
                     CHECK (property_type IN (
                         'sfr',
                         'condo',
                         'coop',
                         'pud',
                         '2_unit',
                         '3_unit',
                         '4_unit',
                         'manufactured',
                         'mixed_use',
                         'commercial',
                         'vacant_land',
                         'other'
                     )),
    usage_type       VARCHAR(30)
                     CHECK (usage_type IN (
                         'primary',
                         'second_home',
                         'investment'
                     )),
    property_state   VARCHAR(2),
    property_county  VARCHAR(100),

    -- Eligibility per agency
    fannie_eligible  BOOLEAN DEFAULT TRUE,
    fha_eligible     BOOLEAN DEFAULT TRUE,
    va_eligible      BOOLEAN DEFAULT TRUE,
    usda_eligible    BOOLEAN DEFAULT FALSE,

    -- Flags
    is_warrantable   BOOLEAN DEFAULT TRUE,
    in_flood_zone    BOOLEAN DEFAULT FALSE,
    flood_zone_type  VARCHAR(10),
    requires_flood_insurance BOOLEAN DEFAULT FALSE,
    is_rural         BOOLEAN DEFAULT FALSE,
    has_age_restriction BOOLEAN DEFAULT FALSE,

    -- Condo specific
    hoa_name         VARCHAR(200),
    hoa_monthly_fee  NUMERIC,
    condo_project_approved BOOLEAN,

    -- Issues found
    ineligibility_reasons TEXT[],
    conditions_required   TEXT[],
    overall_status   VARCHAR(20)
                     CHECK (overall_status IN (
                         'eligible',
                         'eligible_with_conditions',
                         'ineligible',
                         'review_required'
                     )),

    source_document_id VARCHAR(100),
    notes            TEXT,
    created_at       TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(application_id, tenant_id)
);

CREATE INDEX IF NOT EXISTS
    idx_property_eligibility_app
    ON property_eligibility(
        application_id, tenant_id
    );

ALTER TABLE property_eligibility
    ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
  DROP POLICY IF EXISTS pe2_read
      ON property_eligibility;
  CREATE POLICY pe2_read
      ON property_eligibility FOR SELECT
      USING (
          tenant_id = current_setting(
              'app.tenant_id', true
          ) OR current_user = 'edms_admin'
      );
  DROP POLICY IF EXISTS pe2_write
      ON property_eligibility;
  CREATE POLICY pe2_write
      ON property_eligibility
      FOR INSERT WITH CHECK (true);
  DROP POLICY IF EXISTS pe2_update
      ON property_eligibility;
  CREATE POLICY pe2_update
      ON property_eligibility
      FOR UPDATE USING (
          current_user = 'edms_admin'
      );
END $$;

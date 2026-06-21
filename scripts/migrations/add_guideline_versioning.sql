-- scripts/migrations/add_guideline_versioning.sql

-- Add Type 2 SCD columns to agency_guidelines
-- Idempotent — safe to re-run

ALTER TABLE agency_guidelines
  ADD COLUMN IF NOT EXISTS
    version_id      UUID
    DEFAULT gen_random_uuid(),
  ADD COLUMN IF NOT EXISTS
    valid_from      DATE
    NOT NULL DEFAULT CURRENT_DATE,
  ADD COLUMN IF NOT EXISTS
    valid_to        DATE
    DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS
    downloaded_at   TIMESTAMPTZ
    DEFAULT NOW(),
  ADD COLUMN IF NOT EXISTS
    source_revision VARCHAR(200)
    DEFAULT NULL;

-- Point-in-time query index
CREATE INDEX IF NOT EXISTS idx_ag_pit
  ON agency_guidelines(
    agency,
    guideline_name,
    valid_from,
    valid_to
  );

-- Convenience view: current rules only
CREATE OR REPLACE VIEW vw_guidelines_current AS
SELECT *
FROM agency_guidelines
WHERE valid_to IS NULL
AND is_active = true;

-- Point-in-time function
-- Usage: SELECT * FROM agency_guidelines_at('2025-06-15')
CREATE OR REPLACE FUNCTION agency_guidelines_at(
    as_of DATE
)
RETURNS SETOF agency_guidelines
LANGUAGE SQL STABLE AS $$
    SELECT *
    FROM agency_guidelines
    WHERE valid_from <= as_of
    AND (valid_to IS NULL
         OR valid_to >= as_of)
    AND is_active = true
    ORDER BY agency, guideline_name,
             valid_from DESC;
$$;

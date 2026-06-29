-- Add governed_by to conditions_library (workbench data-driven layer).
-- Three-layer provenance for each condition template: federal / agency / tenant.

ALTER TABLE conditions_library
ADD COLUMN IF NOT EXISTS governed_by VARCHAR(20)
DEFAULT 'agency'
CHECK (governed_by IN ('federal', 'agency', 'tenant'));

-- Backfill based on citation text
UPDATE conditions_library SET governed_by = 'federal'
WHERE agency_citation ILIKE '%CFR%'
   OR agency_citation ILIKE '%BSA%'
   OR agency_citation ILIKE '%CFPB%'
   OR agency_citation ILIKE '%USC%'
   OR agency_citation ILIKE '%Reg Z%'
   OR agency_citation ILIKE '%Reg B%'
   OR agency_citation ILIKE '%TRID%'
   OR agency_citation ILIKE '%HMDA%'
   OR agency_citation ILIKE '%ECOA%';

UPDATE conditions_library SET governed_by = 'tenant'
WHERE agency_citation IS NULL
   OR TRIM(agency_citation) = '';

-- Everything else stays 'agency' (FNMA, FHA, VA, HUD, Fannie, Freddie)

-- Add a provenance `source` column to conditions_library.
--
-- All 91 existing rows were hand-authored by the Accord team, so they backfill
-- to 'manual'. No agency connector (fannie_api / freddie_api) or PDF extractor
-- (fha_pdf / va_pdf) is built yet — do NOT infer source from agency_citation or
-- governed_by; every existing row is 'manual'.
--
-- Run as edms_admin (table owner).

ALTER TABLE conditions_library
  ADD COLUMN source VARCHAR(20) NOT NULL DEFAULT 'manual'
  CHECK (source IN ('manual', 'fannie_api', 'fha_pdf', 'va_pdf', 'freddie_api'));

-- Explicit / idempotent backfill (the NOT NULL DEFAULT already sets existing
-- rows to 'manual' at ALTER time, so this matches 0 rows — kept for clarity).
UPDATE conditions_library SET source = 'manual' WHERE source IS NULL;

-- Verification (expected: manual | 91):
--   SELECT source, count(*) FROM conditions_library GROUP BY source;

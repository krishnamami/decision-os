-- RA-P0-A: document_index.s3_key — canonical S3 object key for the raw upload.
-- The column already exists in the live RDS (the documents API reads it); this
-- migration is idempotent and additive so a fresh database matches production.
-- The key is built by core.storage.s3_keys.doc_raw_key (MISMO-aligned hierarchy).

ALTER TABLE document_index ADD COLUMN IF NOT EXISTS s3_key TEXT;

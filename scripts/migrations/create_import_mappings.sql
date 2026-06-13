-- Saved column mappings for non-template CSV imports.
CREATE TABLE IF NOT EXISTS import_mappings (
  mapping_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id VARCHAR NOT NULL,
  mapping_name VARCHAR,
  source_system VARCHAR,            -- encompass, ice, custom
  column_mapping JSONB NOT NULL,
  created_by UUID,
  created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_import_mappings_tenant ON import_mappings(tenant_id);

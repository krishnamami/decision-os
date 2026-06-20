-- ============================================================
-- Evidence Graph — schema (EV-A)
-- Foundation for EV-B..EV-E. Schema only; no persona changes.
--   evidence_nodes : raw evidence extracted from documents
--   evidence_edges : relationships between evidence nodes
--   fact_nodes     : resolved facts personas will consume
-- ============================================================

-- ─────────────────────────────────────────────
-- EVIDENCE NODES — one row per piece of evidence
-- extracted from a document. Links to document_index.
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS evidence_nodes (
    id                   UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    application_id       VARCHAR(50) NOT NULL,
    tenant_id            VARCHAR(50) NOT NULL,
    node_type            VARCHAR(50) NOT NULL
                         CHECK (node_type IN (
                             'document_field', 'derived_fact',
                             'cross_validation', 'conflict', 'resolution')),
    evidence_category    VARCHAR(50) NOT NULL
                         CHECK (evidence_category IN (
                             'income', 'asset', 'credit', 'employment',
                             'property', 'title', 'liability', 'identity',
                             'compliance')),
    field_name           VARCHAR(100) NOT NULL,
    raw_value            TEXT,
    numeric_value        NUMERIC,
    confidence           NUMERIC CHECK (confidence >= 0 AND confidence <= 1),
    source_document_id   VARCHAR(100),
    source_document_type VARCHAR(50),
    extraction_method    VARCHAR(50)
                         CHECK (extraction_method IN (
                             'textract', 'claude_vision', 'regex',
                             'derived', 'manual')),
    tax_year             INTEGER,
    as_of_date           DATE,
    metadata             JSONB DEFAULT '{}',
    created_at           TIMESTAMPTZ DEFAULT NOW(),
    FOREIGN KEY (source_document_id)
        REFERENCES document_index(document_id)
        ON DELETE SET NULL
        DEFERRABLE INITIALLY DEFERRED
);

CREATE INDEX IF NOT EXISTS idx_evidence_nodes_app
    ON evidence_nodes(application_id, tenant_id);
CREATE INDEX IF NOT EXISTS idx_evidence_nodes_category
    ON evidence_nodes(application_id, evidence_category);
CREATE INDEX IF NOT EXISTS idx_evidence_nodes_field
    ON evidence_nodes(application_id, field_name);


-- ─────────────────────────────────────────────
-- EVIDENCE EDGES — relationships between nodes.
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS evidence_edges (
    id             UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    application_id VARCHAR(50) NOT NULL,
    tenant_id      VARCHAR(50) NOT NULL,
    from_node_id   UUID NOT NULL REFERENCES evidence_nodes(id) ON DELETE CASCADE,
    to_node_id     UUID NOT NULL REFERENCES evidence_nodes(id) ON DELETE CASCADE,
    relationship   VARCHAR(50) NOT NULL
                   CHECK (relationship IN (
                       'supports', 'conflicts_with', 'derived_from',
                       'validates', 'supersedes', 'corroborates')),
    strength       NUMERIC DEFAULT 1.0 CHECK (strength >= 0 AND strength <= 1),
    notes          TEXT,
    created_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_evidence_edges_from ON evidence_edges(from_node_id);
CREATE INDEX IF NOT EXISTS idx_evidence_edges_to   ON evidence_edges(to_node_id);


-- ─────────────────────────────────────────────
-- FACT NODES — derived facts resolved from evidence.
-- This is the qualified value personas use.
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS fact_nodes (
    id                UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    application_id    VARCHAR(50) NOT NULL,
    tenant_id         VARCHAR(50) NOT NULL,
    fact_type         VARCHAR(100) NOT NULL
                      CHECK (fact_type IN (
                          'qualifying_income', 'total_obligations',
                          'verified_assets', 'funds_to_close',
                          'governing_credit_score', 'employment_continuity',
                          'property_value', 'title_clear', 'fraud_risk_score',
                          'dti_ratio', 'ltv_ratio')),
    fact_value        NUMERIC,
    fact_text         TEXT,
    confidence        NUMERIC CHECK (confidence >= 0 AND confidence <= 1),
    resolution_method VARCHAR(100),
    evidence_ids      UUID[] DEFAULT '{}',
    conflicts_found   BOOLEAN DEFAULT FALSE,
    conflict_ids      UUID[] DEFAULT '{}',
    resolution_notes  TEXT,
    agency_treatment  JSONB DEFAULT '{}',
    computed_at       TIMESTAMPTZ DEFAULT NOW(),
    valid_until       TIMESTAMPTZ,
    -- DEFERRABLE: save_fact_node() supersedes the prior current fact (sets
    -- old.superseded_by = new.id) inside a transaction BEFORE the new row is
    -- inserted, so this self-FK must validate at commit, not per-statement.
    superseded_by     UUID REFERENCES fact_nodes(id) DEFERRABLE INITIALLY DEFERRED,
    created_at        TIMESTAMPTZ DEFAULT NOW()
);

-- Make the self-FK deferrable on tables created before this clause existed.
ALTER TABLE fact_nodes DROP CONSTRAINT IF EXISTS fact_nodes_superseded_by_fkey;
ALTER TABLE fact_nodes ADD CONSTRAINT fact_nodes_superseded_by_fkey
    FOREIGN KEY (superseded_by) REFERENCES fact_nodes(id)
    DEFERRABLE INITIALLY DEFERRED;

-- Exactly one current (non-superseded) fact per (app, tenant, fact_type).
CREATE UNIQUE INDEX IF NOT EXISTS idx_fact_nodes_current
    ON fact_nodes(application_id, tenant_id, fact_type)
    WHERE superseded_by IS NULL;
CREATE INDEX IF NOT EXISTS idx_fact_nodes_app
    ON fact_nodes(application_id, tenant_id);


-- ─────────────────────────────────────────────
-- RLS — tenant isolation from day one. Reads scoped to
-- current_setting('app.tenant_id'); edms_admin sees all.
-- ─────────────────────────────────────────────
ALTER TABLE evidence_nodes ENABLE ROW LEVEL SECURITY;
ALTER TABLE evidence_edges ENABLE ROW LEVEL SECURITY;
ALTER TABLE fact_nodes     ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS evidence_nodes_tenant_read ON evidence_nodes;
CREATE POLICY evidence_nodes_tenant_read ON evidence_nodes FOR SELECT
    USING (tenant_id = current_setting('app.tenant_id', true) OR current_user = 'edms_admin');
DROP POLICY IF EXISTS evidence_edges_tenant_read ON evidence_edges;
CREATE POLICY evidence_edges_tenant_read ON evidence_edges FOR SELECT
    USING (tenant_id = current_setting('app.tenant_id', true) OR current_user = 'edms_admin');
DROP POLICY IF EXISTS fact_nodes_tenant_read ON fact_nodes;
CREATE POLICY fact_nodes_tenant_read ON fact_nodes FOR SELECT
    USING (tenant_id = current_setting('app.tenant_id', true) OR current_user = 'edms_admin');

DROP POLICY IF EXISTS evidence_nodes_write ON evidence_nodes;
CREATE POLICY evidence_nodes_write ON evidence_nodes FOR INSERT WITH CHECK (true);
DROP POLICY IF EXISTS evidence_edges_write ON evidence_edges;
CREATE POLICY evidence_edges_write ON evidence_edges FOR INSERT WITH CHECK (true);
DROP POLICY IF EXISTS fact_nodes_write ON fact_nodes;
CREATE POLICY fact_nodes_write ON fact_nodes FOR INSERT WITH CHECK (true);

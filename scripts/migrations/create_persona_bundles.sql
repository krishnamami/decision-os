-- persona_bundles: frozen snapshot of what each persona saw (RA-3F).
-- Written AFTER decision_outputs commits (best-effort, never blocks the
-- decision). is_current=true = latest version for this persona+application;
-- older versions kept for audit/replay with is_current=false.
--
-- SCHEMA NOTES (verified against live RDS 2026-06-22):
--   * application_id / tenant_id are TEXT (character varying) here and in
--     decision_outputs / entity_states — NOT uuid. The draft's UUID type was
--     wrong; an app id is e.g. 'APP-MRID-SC09'.
--   * persona_id holds the decision_id (one persona == one decision_id in the
--     lending domain, e.g. 'title_assessment'). decision_outputs keys on
--     decision_id, so the FK back-write matches on the exact row id.
--   * Uniqueness is scoped by tenant_id (multi-tenant: meridian + summit +
--     demo). decision_outputs is keyed (application_id, decision_id, tenant_id),
--     so persona_bundles follows the same grain.

CREATE TABLE IF NOT EXISTS persona_bundles (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    application_id   TEXT NOT NULL,
    tenant_id        TEXT NOT NULL,
    persona_id       TEXT NOT NULL,              -- == decision_id
    version          INTEGER NOT NULL DEFAULT 1,
    is_current       BOOLEAN NOT NULL DEFAULT true,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- What the persona actually saw (frozen at run time)
    entity_snapshot   JSONB NOT NULL DEFAULT '{}',
    evidence_snapshot JSONB NOT NULL DEFAULT '{}',
    rules_snapshot    JSONB NOT NULL DEFAULT '{}',
    upstream_snapshot JSONB NOT NULL DEFAULT '{}'
);

-- Only one current bundle per persona per application per tenant
CREATE UNIQUE INDEX IF NOT EXISTS
    persona_bundles_current_unique
    ON persona_bundles (application_id, persona_id, tenant_id)
    WHERE is_current = true;

-- Version uniqueness
CREATE UNIQUE INDEX IF NOT EXISTS
    persona_bundles_version_unique
    ON persona_bundles (application_id, persona_id, tenant_id, version);

-- Fast current reads
CREATE INDEX IF NOT EXISTS
    persona_bundles_current_idx
    ON persona_bundles (application_id, persona_id, tenant_id, is_current);

-- Audit / replay reads (newest version first)
CREATE INDEX IF NOT EXISTS
    persona_bundles_history_idx
    ON persona_bundles (application_id, persona_id, tenant_id, version DESC);

-- Add bundle_id FK to decision_outputs (nullable — NULL for pre-RA-3F decisions)
ALTER TABLE decision_outputs
    ADD COLUMN IF NOT EXISTS bundle_id UUID
    REFERENCES persona_bundles(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS
    decision_outputs_bundle_idx
    ON decision_outputs (bundle_id)
    WHERE bundle_id IS NOT NULL;

-- ============================================================
-- Decision OS — context_store durable schema
-- ------------------------------------------------------------
-- Two append-only tables:
--   1) context_records   — versioned entity state, supersession
--                          chain, tombstone markers, lineage.
--   2) context_snapshots — frozen merge handed to a decision agent;
--                          captures the exact records the agent saw
--                          so a trace can replay inputs verbatim.
--
-- Hard rules backed here:
--   no_context_without_lineage     — lineage JSONB is NOT NULL.
--   no_execution_without_trace     — snapshot row pinned to its
--                                    constituent record_ids.
--   append-only history            — no UPDATE removes data; the
--                                    only mutation is flipping
--                                    superseded_at + superseded_by
--                                    on the previous active row.
-- ============================================================

CREATE TABLE IF NOT EXISTS context_records (
    id              UUID         PRIMARY KEY,
    entity_type     TEXT         NOT NULL,
    entity_id       TEXT         NOT NULL,
    decision_id     TEXT,                                  -- NULL = shared scope
    version         INTEGER      NOT NULL,
    value           JSONB        NOT NULL,
    lineage         JSONB        NOT NULL,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),   -- physical write time
    superseded_at   TIMESTAMPTZ,
    superseded_by   UUID,
    tombstoned_at   TIMESTAMPTZ                            -- NOT NULL on tombstone rows
);

-- Active-row lookup: one row per (entity, scope) where superseded_at IS NULL
-- and tombstoned_at IS NULL. Partial unique index enforces it.
CREATE UNIQUE INDEX IF NOT EXISTS context_records_active_uniq
    ON context_records (entity_type, entity_id, COALESCE(decision_id, ''))
    WHERE superseded_at IS NULL AND tombstoned_at IS NULL;

-- Version monotonicity per scope.
CREATE UNIQUE INDEX IF NOT EXISTS context_records_version_uniq
    ON context_records (entity_type, entity_id, COALESCE(decision_id, ''), version);

-- History scans (DESC version) — used by both get_latest and history().
CREATE INDEX IF NOT EXISTS context_records_entity_version_idx
    ON context_records (entity_type, entity_id, decision_id, version DESC);

-- Point-in-time reads filter by created_at and superseded_at.
CREATE INDEX IF NOT EXISTS context_records_pit_idx
    ON context_records (entity_type, entity_id, decision_id, created_at);

-- Foreign key from new active row to the row it supersedes. Self FK so
-- the chain is queryable; ON DELETE NO ACTION because nothing should
-- ever delete from this table.
ALTER TABLE context_records
    DROP CONSTRAINT IF EXISTS context_records_supersedes_fk;
ALTER TABLE context_records
    ADD  CONSTRAINT context_records_supersedes_fk
    FOREIGN KEY (superseded_by) REFERENCES context_records (id);


CREATE TABLE IF NOT EXISTS context_snapshots (
    id                     UUID         PRIMARY KEY,
    application_id         TEXT         NOT NULL,
    decision_id            TEXT         NOT NULL,
    snapshot_at            TIMESTAMPTZ  NOT NULL DEFAULT now(),
    context                JSONB        NOT NULL,
    record_ids             UUID[]       NOT NULL,
    upstream_decision_ids  TEXT[]       NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS context_snapshots_app_decision_idx
    ON context_snapshots (application_id, decision_id, snapshot_at DESC);

CREATE INDEX IF NOT EXISTS context_snapshots_decision_idx
    ON context_snapshots (decision_id, snapshot_at DESC);

-- RA-7B: adverse_action_notices — ECOA / Reg B §1002.9 notice tracking.
-- One row per declined application; tracks the 30-day notice deadline + the
-- HMDA denial reason codes. Population is a downstream job reading declined
-- underwriting_decision outputs (the persona emits the notice DATA into
-- decision_outputs.context_snapshot.adverse_action). Additive — no existing
-- table or row is touched.

CREATE TABLE IF NOT EXISTS adverse_action_notices (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    application_id  TEXT NOT NULL,
    tenant_id       TEXT NOT NULL,
    decision_id     UUID REFERENCES decision_outputs(id),
    notice_date     TIMESTAMPTZ DEFAULT NOW(),
    notice_deadline TIMESTAMPTZ NOT NULL,
    hmda_codes      INTEGER[] NOT NULL,
    denial_reasons  JSONB NOT NULL,
    status          TEXT DEFAULT 'pending',
    sent_at         TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_aan_application
    ON adverse_action_notices(application_id, tenant_id);

CREATE INDEX IF NOT EXISTS idx_aan_deadline
    ON adverse_action_notices(notice_deadline)
    WHERE status = 'pending';

-- One notice per (application, decision) — lets the population job upsert.
CREATE UNIQUE INDEX IF NOT EXISTS idx_aan_app_decision
    ON adverse_action_notices(application_id, tenant_id, decision_id);

-- ─────────────────────────────────────────────────────────────────────────────
-- Accord workbench schema: assignments, communications, attention requests,
-- loan notes, conditions, notifications, and loan-lifecycle columns.
--
-- Idempotent (IF NOT EXISTS throughout) so it is safe to re-run.
--   python scripts/migrations/run_workbench_migration.py
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS loan_assignments (
  assignment_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  application_id VARCHAR NOT NULL,
  tenant_id VARCHAR NOT NULL,
  assigned_to UUID REFERENCES users(user_id),
  assigned_by UUID REFERENCES users(user_id),
  stage VARCHAR NOT NULL,  -- verify | underwrite | eligibility | decide | close
  status VARCHAR NOT NULL DEFAULT 'active',
    -- active: in user's queue
    -- pending_borrower: waiting for borrower response
    -- pending_internal: waiting for internal attention request
    -- decided: decision made, moved to next stage
    -- funded: loan closed and funded
    -- denied: loan denied
  previous_assignee UUID,
  handoff_notes TEXT,
  assigned_at TIMESTAMP DEFAULT NOW(),
  completed_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS communications (
  comm_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  application_id VARCHAR NOT NULL,
  tenant_id VARCHAR NOT NULL,
  type VARCHAR NOT NULL,  -- doc_request | status_update | borrower_response | lo_notification
  direction VARCHAR NOT NULL,  -- outbound | inbound
  from_user_id UUID,
  recipient_email VARCHAR,
  subject TEXT,
  body TEXT,
  items_requested JSONB,  -- checklist of docs requested
  status VARCHAR DEFAULT 'simulated',  -- simulated | sent | delivered | failed
  due_date DATE,
  responded_at TIMESTAMP,
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS attention_requests (
  request_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  application_id VARCHAR NOT NULL,
  tenant_id VARCHAR NOT NULL,
  from_user_id UUID NOT NULL REFERENCES users(user_id),
  to_user_id UUID NOT NULL REFERENCES users(user_id),
  decision_id VARCHAR,  -- which persona decision needs revisiting
  message TEXT NOT NULL,
  priority VARCHAR DEFAULT 'normal',  -- normal | urgent
  status VARCHAR DEFAULT 'open',  -- open | in_progress | completed | dismissed
  response TEXT,
  created_at TIMESTAMP DEFAULT NOW(),
  completed_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS loan_notes (
  note_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  application_id VARCHAR NOT NULL,
  tenant_id VARCHAR NOT NULL,
  user_id UUID NOT NULL REFERENCES users(user_id),
  note TEXT NOT NULL,
  note_type VARCHAR DEFAULT 'general',  -- general | handoff | condition | escalation
  created_at TIMESTAMP DEFAULT NOW()
);

-- NB: named loan_conditions (not `conditions`) — an EDMS `conditions` table
-- already exists with a different (decision/severity) schema.
CREATE TABLE IF NOT EXISTS loan_conditions (
  condition_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  application_id VARCHAR NOT NULL,
  tenant_id VARCHAR NOT NULL,
  condition_text TEXT NOT NULL,
  condition_type VARCHAR NOT NULL,  -- ptd (prior-to-docs) | ptc (prior-to-close) | ptf (prior-to-fund)
  assigned_to UUID REFERENCES users(user_id),
  created_by UUID REFERENCES users(user_id),
  due_date DATE,
  status VARCHAR DEFAULT 'outstanding',  -- outstanding | in_progress | satisfied | waived
  satisfied_by UUID,
  satisfied_at TIMESTAMP,
  notes TEXT,
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS notifications (
  notification_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id VARCHAR NOT NULL,
  user_id UUID NOT NULL REFERENCES users(user_id),
  type VARCHAR NOT NULL,  -- borrower_responded | loan_assigned | attention_request | rate_lock_warning | escalation | decision_made
  title TEXT NOT NULL,
  body TEXT,
  application_id VARCHAR,
  is_read BOOLEAN DEFAULT false,
  created_at TIMESTAMP DEFAULT NOW()
);

-- Add lifecycle columns to entity_states if not exist
ALTER TABLE entity_states ADD COLUMN IF NOT EXISTS loan_status VARCHAR DEFAULT 'active';
ALTER TABLE entity_states ADD COLUMN IF NOT EXISTS current_stage VARCHAR DEFAULT 'verify';
ALTER TABLE entity_states ADD COLUMN IF NOT EXISTS assigned_to UUID;

CREATE INDEX IF NOT EXISTS idx_assignments_user ON loan_assignments(assigned_to, status);
CREATE INDEX IF NOT EXISTS idx_assignments_app ON loan_assignments(application_id);
CREATE INDEX IF NOT EXISTS idx_attention_to ON attention_requests(to_user_id, status);
CREATE INDEX IF NOT EXISTS idx_notes_app ON loan_notes(application_id);
CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id, is_read);
CREATE INDEX IF NOT EXISTS idx_loan_conditions_app ON loan_conditions(application_id);

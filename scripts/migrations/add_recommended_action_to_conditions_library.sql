-- Add recommended_action to conditions_library (workbench data-driven layer).
-- The default UW action surfaced for each condition category.

ALTER TABLE conditions_library
ADD COLUMN IF NOT EXISTS recommended_action VARCHAR(50)
DEFAULT 'request_documents'
CHECK (recommended_action IN (
    'refer_bsa', 'request_documents', 'escalate',
    'senior_review', 'add_note', 'view_details'
));

-- Backfill
UPDATE conditions_library SET recommended_action = 'refer_bsa'
WHERE category = 'fraud';

UPDATE conditions_library SET recommended_action = 'escalate'
WHERE category IN ('product', 'compliance');

UPDATE conditions_library SET recommended_action = 'request_documents'
WHERE category IN ('income', 'asset', 'credit', 'employment', 'title');

UPDATE conditions_library SET recommended_action = 'view_details'
WHERE category IN ('closing', 'property');

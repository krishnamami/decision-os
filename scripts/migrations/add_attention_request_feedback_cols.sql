-- Senior-UW feedback flow: attention_requests gains a structured category and a
-- source marker so a request can be rendered as the "FEEDBACK FROM SENIOR UW"
-- variant (source='senior_uw_feedback') distinct from a plain review request.
-- Additive, nullable — existing rows unaffected. Run as edms_admin.

ALTER TABLE attention_requests ADD COLUMN IF NOT EXISTS category VARCHAR(20);
ALTER TABLE attention_requests ADD COLUMN IF NOT EXISTS source   VARCHAR(30);

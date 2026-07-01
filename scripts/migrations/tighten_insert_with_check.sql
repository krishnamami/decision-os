-- Tighten the *_write INSERT policies from WITH CHECK (true) to tenant-scoped,
-- so inserts are constrained to the caller's tenant at the DB layer (defense in
-- depth; the app already sets tenant_id from the JWT).
--
-- Scope: the 16 tenant-scoped tables with a dedicated INSERT policy. The 17th
-- INSERT policy — catalogue_staging_insert — is intentionally EXCLUDED because
-- catalogue_staging has no tenant_id column (shared governance-staging table).
--
-- Expression matches the QA-C Step 3 tenant policies: tenant match OR the
-- 'accord_admin' sentinel (platform/cross-tenant). Migrations run as edms_admin,
-- which bypasses RLS, so they are unaffected. Run as edms_admin.

ALTER POLICY aa_write             ON asset_accounts           WITH CHECK (((tenant_id)::text = current_setting('app.tenant_id'::text, true)) OR (current_setting('app.tenant_id'::text, true) = 'accord_admin'::text));
ALTER POLICY ad_write             ON asset_deposits           WITH CHECK (((tenant_id)::text = current_setting('app.tenant_id'::text, true)) OR (current_setting('app.tenant_id'::text, true) = 'accord_admin'::text));
ALTER POLICY cd_write             ON condition_documents      WITH CHECK (((tenant_id)::text = current_setting('app.tenant_id'::text, true)) OR (current_setting('app.tenant_id'::text, true) = 'accord_admin'::text));
ALTER POLICY cf_write             ON credit_findings          WITH CHECK (((tenant_id)::text = current_setting('app.tenant_id'::text, true)) OR (current_setting('app.tenant_id'::text, true) = 'accord_admin'::text));
ALTER POLICY ct_write             ON credit_tradelines        WITH CHECK (((tenant_id)::text = current_setting('app.tenant_id'::text, true)) OR (current_setting('app.tenant_id'::text, true) = 'accord_admin'::text));
ALTER POLICY dal_insert           ON decision_audit_log       WITH CHECK (((tenant_id)::text = current_setting('app.tenant_id'::text, true)) OR (current_setting('app.tenant_id'::text, true) = 'accord_admin'::text));
ALTER POLICY dt_insert            ON decision_trace           WITH CHECK (((tenant_id)::text = current_setting('app.tenant_id'::text, true)) OR (current_setting('app.tenant_id'::text, true) = 'accord_admin'::text));
ALTER POLICY evidence_edges_write ON evidence_edges           WITH CHECK (((tenant_id)::text = current_setting('app.tenant_id'::text, true)) OR (current_setting('app.tenant_id'::text, true) = 'accord_admin'::text));
ALTER POLICY evidence_nodes_write ON evidence_nodes           WITH CHECK (((tenant_id)::text = current_setting('app.tenant_id'::text, true)) OR (current_setting('app.tenant_id'::text, true) = 'accord_admin'::text));
ALTER POLICY fact_nodes_write     ON fact_nodes               WITH CHECK (((tenant_id)::text = current_setting('app.tenant_id'::text, true)) OR (current_setting('app.tenant_id'::text, true) = 'accord_admin'::text));
ALTER POLICY fs_write             ON fraud_signals            WITH CHECK (((tenant_id)::text = current_setting('app.tenant_id'::text, true)) OR (current_setting('app.tenant_id'::text, true) = 'accord_admin'::text));
ALTER POLICY lci_write            ON loan_condition_instances WITH CHECK (((tenant_id)::text = current_setting('app.tenant_id'::text, true)) OR (current_setting('app.tenant_id'::text, true) = 'accord_admin'::text));
ALTER POLICY oc_write             ON ownership_chain          WITH CHECK (((tenant_id)::text = current_setting('app.tenant_id'::text, true)) OR (current_setting('app.tenant_id'::text, true) = 'accord_admin'::text));
ALTER POLICY pe2_write            ON property_eligibility     WITH CHECK (((tenant_id)::text = current_setting('app.tenant_id'::text, true)) OR (current_setting('app.tenant_id'::text, true) = 'accord_admin'::text));
ALTER POLICY pe_write             ON property_encumbrances    WITH CHECK (((tenant_id)::text = current_setting('app.tenant_id'::text, true)) OR (current_setting('app.tenant_id'::text, true) = 'accord_admin'::text));
ALTER POLICY tf_write             ON title_findings           WITH CHECK (((tenant_id)::text = current_setting('app.tenant_id'::text, true)) OR (current_setting('app.tenant_id'::text, true) = 'accord_admin'::text));

-- catalogue_staging_insert: intentionally left WITH CHECK (true) — no tenant_id.
-- Verify: SELECT tablename, policyname, with_check FROM pg_policies
--         WHERE schemaname='public' AND cmd='INSERT';  -- 16 tenant-scoped, 1 true.

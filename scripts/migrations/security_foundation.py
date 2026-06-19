"""Security foundation (Option 1 — safe, no enforcement).

Creates the DB service roles, grants, RLS policies, and the role_permissions
table. ALL INERT under the current app DB user (edms_admin has BYPASSRLS), so
nothing in production changes behaviour. This is scaffolding for a future
enforcement step (switching the app to a non-bypass role + per-acquire
app.tenant_id). No table has ENABLE/FORCE ROW LEVEL SECURITY toggled here.

Idempotent.

  python scripts/migrations/security_foundation.py
"""
import asyncio
import os

from dotenv import load_dotenv

load_dotenv()

DDL = r"""
-- 1. Service roles ---------------------------------------------------------
DO $$ BEGIN CREATE ROLE accord_app NOLOGIN NOINHERIT;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE ROLE accord_readonly NOLOGIN NOINHERIT;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE ROLE governance_admin NOLOGIN NOINHERIT;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- 2. accord_app grants -----------------------------------------------------
GRANT SELECT ON entity_states, applications, applicants, tenants, users,
  indexing_watermarks, regulatory_rules, agency_guidelines, tenant_rules,
  rate_sheet_entry TO accord_app;
GRANT SELECT ON vw_compliance_check_context, vw_credit_assessment_context,
  vw_income_verification_context, vw_product_eligibility_context,
  vw_closing_readiness_context TO accord_app;
GRANT SELECT, INSERT, UPDATE ON decision_outputs, decision_timeline,
  document_index, entity_states, applications, applicants TO accord_app;

-- 3. accord_readonly grants ------------------------------------------------
GRANT SELECT ON entity_states, decision_outputs, decision_timeline,
  applications, document_index, vw_compliance_check_context,
  vw_credit_assessment_context, vw_income_verification_context,
  vw_product_eligibility_context, vw_closing_readiness_context
  TO accord_readonly;

-- 4. governance_admin: shared catalogue only -------------------------------
GRANT ALL ON regulatory_rules, agency_guidelines TO governance_admin;
REVOKE INSERT, UPDATE, DELETE ON regulatory_rules, agency_guidelines
  FROM accord_app;

-- 5. Department roles inherit service roles --------------------------------
GRANT accord_app TO credit_underwriter, income_underwriter, senior_underwriter,
  employment_specialist, collateral_analyst, closer_role;
GRANT accord_readonly TO compliance_officer, fraud_analyst, pricing_analyst,
  product_specialist, post_closer;

-- 6. RLS policies (inert; edms_admin bypasses) -----------------------------
DROP POLICY IF EXISTS rls_entity_states ON entity_states;
CREATE POLICY rls_entity_states ON entity_states FOR ALL
  USING (tenant_id::text = current_setting('app.tenant_id', true)
         OR current_setting('app.tenant_id', true) = 'accord_admin');

DROP POLICY IF EXISTS rls_document_index ON document_index;
CREATE POLICY rls_document_index ON document_index FOR ALL
  USING (tenant_id::text = current_setting('app.tenant_id', true)
         OR current_setting('app.tenant_id', true) = 'accord_admin');

DROP POLICY IF EXISTS rls_applications ON applications;
CREATE POLICY rls_applications ON applications FOR ALL
  USING (tenant_id::text = current_setting('app.tenant_id', true)
         OR current_setting('app.tenant_id', true) = 'accord_admin');

DROP POLICY IF EXISTS rls_decision_outputs ON decision_outputs;
CREATE POLICY rls_decision_outputs ON decision_outputs FOR ALL
  USING (tenant_id::text = current_setting('app.tenant_id', true)
         OR current_setting('app.tenant_id', true) = 'accord_admin');

DROP POLICY IF EXISTS rls_decision_timeline ON decision_timeline;
CREATE POLICY rls_decision_timeline ON decision_timeline FOR ALL
  USING (tenant_id::text = current_setting('app.tenant_id', true)
         OR current_setting('app.tenant_id', true) = 'accord_admin');

DROP POLICY IF EXISTS rls_applicants ON applicants;
CREATE POLICY rls_applicants ON applicants FOR ALL
  USING (EXISTS (SELECT 1 FROM applications a
                 WHERE (a.applicant_id = applicants.applicant_id
                        OR a.co_applicant_id = applicants.applicant_id)
                   AND a.tenant_id::text = current_setting('app.tenant_id', true))
         OR current_setting('app.tenant_id', true) = 'accord_admin');

DROP POLICY IF EXISTS rls_tenant_rules ON tenant_rules;
CREATE POLICY rls_tenant_rules ON tenant_rules FOR ALL
  USING (tenant_id::text = current_setting('app.tenant_id', true)
         OR current_setting('app.tenant_id', true) = 'accord_admin');

DROP POLICY IF EXISTS rls_rate_sheet ON rate_sheet_entry;
CREATE POLICY rls_rate_sheet ON rate_sheet_entry FOR ALL
  USING (tenant_id::text = current_setting('app.tenant_id', true)
         OR current_setting('app.tenant_id', true) = 'accord_admin');

-- 7. role_permissions table (app-level RBAC; no DB enforcement) ------------
CREATE TABLE IF NOT EXISTS role_permissions (
    role_name    VARCHAR PRIMARY KEY,
    display_name VARCHAR NOT NULL,
    permissions  JSONB NOT NULL DEFAULT '{}',
    created_at   TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO role_permissions (role_name, display_name, permissions) VALUES
('underwriter', 'Underwriter', '{"view_decisions":true,"view_workbench":true,"add_notes":true,"request_documents":true,"override_decision":false,"approve_exception":false,"manage_users":false,"manage_policy":false,"export_reports":false,"view_all_loans":true,"delete_anything":false}'),
('senior_uw', 'Senior Underwriter', '{"view_decisions":true,"view_workbench":true,"add_notes":true,"request_documents":true,"override_decision":true,"approve_exception":true,"manage_users":false,"manage_policy":false,"export_reports":true,"view_all_loans":true,"delete_anything":false}'),
('compliance', 'Compliance Officer', '{"view_decisions":true,"view_workbench":true,"add_notes":true,"request_documents":false,"override_decision":false,"approve_exception":false,"manage_users":false,"manage_policy":false,"export_reports":true,"view_all_loans":true,"delete_anything":false}'),
('admin', 'Tenant Administrator', '{"view_decisions":true,"view_workbench":true,"add_notes":true,"request_documents":true,"override_decision":true,"approve_exception":true,"manage_users":true,"manage_policy":true,"export_reports":true,"view_all_loans":true,"delete_anything":false}'),
('read_only', 'Read Only', '{"view_decisions":true,"view_workbench":true,"add_notes":false,"request_documents":false,"override_decision":false,"approve_exception":false,"manage_users":false,"manage_policy":false,"export_reports":false,"view_all_loans":true,"delete_anything":false}')
ON CONFLICT (role_name) DO UPDATE SET permissions = EXCLUDED.permissions;
"""

VERIFY = """
SELECT 'roles' AS check_type, rolname AS name, 'exists' AS status
FROM pg_roles WHERE rolname IN ('accord_app','accord_readonly','governance_admin')
UNION ALL
SELECT 'role_permissions', role_name, 'seeded' FROM role_permissions
UNION ALL
SELECT 'policies', tablename, policyname FROM pg_policies
WHERE schemaname='public' AND policyname LIKE 'rls_%'
ORDER BY check_type, name;
"""


async def main():
    import asyncpg
    url = os.environ['DATABASE_URL'].replace('+asyncpg', '').replace('postgresql+psycopg2', 'postgresql')
    conn = await asyncpg.connect(url)
    try:
        await conn.execute(DDL)
        print("DDL applied (roles, grants, policies, role_permissions).\n")
        ct = None
        for r in await conn.fetch(VERIFY):
            if r['check_type'] != ct:
                ct = r['check_type']
                print(f"=== {ct} ===")
            print(f"  {r['name']:<28} {r['status']}")
    finally:
        await conn.close()


asyncio.run(main())

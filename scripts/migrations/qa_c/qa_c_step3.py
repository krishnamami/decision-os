"""QA-C Step 3 — RLS policy cleanup + view security_invoker.

Runs as edms_admin (owner) via DATABASE_URL. All 43 ALTERs (21 policies + 22
views) run in ONE transaction — all-or-nothing. Prints verification only.

Inert until Step 5: the app still connects as edms_admin (bypassrls), so these
changes don't alter live behaviour yet.
"""
import asyncio
import os

# tenant-scope + accord_admin sentinel (replaces the edms_admin-by-name bypass)
TOA = ("((tenant_id)::text = current_setting('app.tenant_id'::text, true)) "
       "OR (current_setting('app.tenant_id'::text, true) = 'accord_admin'::text)")
GOV = "(CURRENT_USER = 'governance_admin'::name)"

READ_POLICIES = [
    ("aa_read", "asset_accounts"),
    ("ad_read", "asset_deposits"),
    ("cd_read", "condition_documents"),
    ("cf_read", "credit_findings"),
    ("ct_read", "credit_tradelines"),
    ("dal_read", "decision_audit_log"),
    ("dt_read", "decision_trace"),
    ("evidence_edges_tenant_read", "evidence_edges"),
    ("evidence_nodes_tenant_read", "evidence_nodes"),
    ("fact_nodes_tenant_read", "fact_nodes"),
    ("fs_read", "fraud_signals"),
    ("lci_read", "loan_condition_instances"),
    ("oc_read", "ownership_chain"),
    ("pe2_read", "property_eligibility"),
    ("pe_read", "property_encumbrances"),
    ("tf_read", "title_findings"),
]

VIEWS = [
    "vw_approval_routing_context", "vw_asset_verification_context",
    "vw_closing_readiness_context", "vw_compliance_check_context",
    "vw_credit_assessment_context", "vw_dti_calculation_context",
    "vw_employment_gaps", "vw_employment_reconciliation_context",
    "vw_fraud_screening_context", "vw_guidelines_current", "vw_hmda_reporting",
    "vw_income_verification_context", "vw_loan_condition_summary",
    "vw_loan_conditions_aggregate", "vw_ltv_assessment_context",
    "vw_pipeline_status", "vw_product_eligibility_context",
    "vw_rate_pricing_context", "vw_regulation_transparency",
    "vw_title_assessment_context", "vw_underwriting_decision_context",
    "document_graph",
]


def build_statements():
    stmts = []
    # Part A — 16 read policies
    for pol, tbl in READ_POLICIES:
        stmts.append(f"ALTER POLICY {pol} ON {tbl} USING ({TOA})")
    # Part B — 4 UPDATE policies (add tenant fallback)
    stmts.append(f"ALTER POLICY dt_update ON decision_trace USING ({TOA})")
    stmts.append(f"ALTER POLICY pe2_update ON property_eligibility USING ({TOA})")
    stmts.append(f"ALTER POLICY fs_update ON fraud_signals USING ({TOA} OR {GOV})")
    stmts.append(f"ALTER POLICY lci_update ON loan_condition_instances USING ({TOA} OR {GOV})")
    # Part C — catalogue_staging_approve (swap edms_admin -> sentinel, keep governance_admin)
    stmts.append(
        "ALTER POLICY catalogue_staging_approve ON catalogue_staging "
        f"USING ({GOV} OR (current_setting('app.tenant_id'::text, true) = 'accord_admin'::text))")
    # Part D — 22 views security_invoker=true
    for v in VIEWS:
        stmts.append(f"ALTER VIEW public.{v} SET (security_invoker = true)")
    return stmts


async def main():
    import asyncpg
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    stmts = build_statements()
    print(f"Executing {len(stmts)} ALTERs in one transaction "
          f"({len(READ_POLICIES) + 5} policies + {len(VIEWS)} views)...")
    try:
        async with conn.transaction():
            for s in stmts:
                await conn.execute(s)
        print("Step 3 committed OK.\n")
    except Exception as e:  # noqa: BLE001
        print("Step 3 FAILED — transaction rolled back:", repr(e))
        await conn.close()
        raise SystemExit(1)

    # ---- verification ----
    print("=== 1) policies still referencing edms_admin (expect NONE) ===")
    left = await conn.fetch(
        """SELECT tablename, policyname FROM pg_policies
           WHERE schemaname='public'
             AND (coalesce(qual,'') ILIKE '%edms_admin%'
                  OR coalesce(with_check,'') ILIKE '%edms_admin%')
           ORDER BY tablename, policyname""")
    print(f"count = {len(left)}")
    for r in left:
        print("  STILL PRESENT:", dict(r))

    print("\n=== 2) views WITHOUT security_invoker=true (expect NONE) ===")
    missing = await conn.fetch(
        """SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
           WHERE c.relkind='v' AND n.nspname='public'
             AND (c.reloptions IS NULL OR NOT (c.reloptions @> ARRAY['security_invoker=true']))
           ORDER BY 1""")
    total_views = await conn.fetchval(
        "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE c.relkind='v' AND n.nspname='public'")
    with_si = await conn.fetchval(
        "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE c.relkind='v' AND n.nspname='public' "
        "AND c.reloptions @> ARRAY['security_invoker=true']")
    print(f"views total={total_views}, security_invoker=true={with_si}, missing={len(missing)}")
    for r in missing:
        print("  MISSING:", r["relname"])

    print("\n=== 3a) sanity: governance_admin retained where expected ===")
    gov = await conn.fetch(
        """SELECT tablename, policyname FROM pg_policies
           WHERE schemaname='public' AND coalesce(qual,'') ILIKE '%governance_admin%'
           ORDER BY tablename, policyname""")
    for r in gov:
        print("  ", dict(r))

    print("\n=== 3b) app behaviour unchanged (edms_admin still bypasses RLS) ===")
    who = await conn.fetchrow("SELECT current_user, session_user")
    role = await conn.fetchrow(
        "SELECT rolname, rolbypassrls FROM pg_roles WHERE rolname='edms_admin'")
    print("  connection:", dict(who))
    print("  edms_admin:", dict(role))
    tenants = await conn.fetch(
        "SELECT tenant_id, count(*) AS n FROM entity_states GROUP BY tenant_id ORDER BY tenant_id")
    print("  entity_states tenants visible as edms_admin (expect ALL — bypass intact):")
    for t in tenants:
        print("   ", dict(t))

    await conn.close()


asyncio.run(main())

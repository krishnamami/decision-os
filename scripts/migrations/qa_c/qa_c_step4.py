"""QA-C Step 4 — RLS tenant-isolation test.

Setup/cleanup run as edms_admin (reliable fixture mgmt, bypasses RLS). The 5
isolation CHECKS connect as accord_app (RLS ENFORCED — non-owner, non-bypass).
'qa_c_test' is a throwaway tenant that exists ONLY as disposable data rows (not
added to the tenants registry); RLS scopes purely on the tenant_id column, so
this is a genuine isolated tenant for the test. Cleanup runs in finally,
pass or fail. accord_app password comes from the ACCORD_APP_PWD env override.
"""
import asyncio
import os

TEN = "qa_c_test"
APPS = ["QA_C_TEST_001", "QA_C_TEST_002", "QA_C_TEST_003"]
A0 = APPS[0]
CHILD_TABLES = ["decision_trace", "fraud_signals",
                "loan_condition_instances", "property_eligibility"]
ALL_TABLES = ["entity_states"] + CHILD_TABLES


def rc(status: str) -> int:
    # asyncpg execute() returns e.g. 'UPDATE 1' / 'DELETE 3'
    return int(status.split()[-1])


async def vis(conn):
    """(row count, sorted distinct tenant_ids) visible in entity_states now."""
    r = await conn.fetchrow(
        "SELECT count(*) AS n, array_agg(DISTINCT tenant_id) AS ts FROM entity_states")
    return r["n"], sorted(r["ts"] or [])


async def set_local(conn, tenant):
    await conn.execute("SELECT set_config('app.tenant_id', $1, true)", tenant)


async def run_checks(app, results):
    # (a) tenant=summit -> only summit visible, qa_c_test invisible
    async with app.transaction():
        await set_local(app, "summit")
        n, ts = await vis(app)
        qa = await app.fetchval(
            "SELECT count(*) FROM entity_states WHERE tenant_id=$1", TEN)
    results["a"] = {"pass": ts == ["summit"] and qa == 0 and n > 0,
                    "visible_tenants": ts, "summit_rows": n, "qa_c_test_rows": qa}

    # (b) tenant=qa_c_test -> only test rows visible, summit invisible
    async with app.transaction():
        await set_local(app, TEN)
        n, ts = await vis(app)
        sm = await app.fetchval(
            "SELECT count(*) FROM entity_states WHERE tenant_id='summit'")
    results["b"] = {"pass": ts == [TEN] and n == len(APPS) and sm == 0,
                    "visible_tenants": ts, "qa_c_test_rows": n, "summit_rows": sm}

    # (c) tenant=accord_admin sentinel -> all tenants visible
    async with app.transaction():
        await set_local(app, "accord_admin")
        n, ts = await vis(app)
    results["c"] = {"pass": "summit" in ts and TEN in ts and len(ts) >= 8,
                    "visible_tenants": ts, "distinct_count": len(ts)}

    # (d) the 4 UPDATE paths: allowed for current tenant, denied (0 rows) cross-tenant
    own, cross = {}, {}
    async with app.transaction():
        await set_local(app, TEN)
        own["decision_trace"] = rc(await app.execute(
            "UPDATE decision_trace SET review_notes='qa' WHERE application_id=$1", A0))
        own["fraud_signals"] = rc(await app.execute(
            "UPDATE fraud_signals SET resolution_notes='qa' WHERE application_id=$1", A0))
        own["loan_condition_instances"] = rc(await app.execute(
            "UPDATE loan_condition_instances SET notes='qa' WHERE application_id=$1", A0))
        own["property_eligibility"] = rc(await app.execute(
            "UPDATE property_eligibility SET notes='qa' WHERE application_id=$1", A0))
    async with app.transaction():
        await set_local(app, "summit")  # different tenant must NOT touch qa_c_test rows
        for t in CHILD_TABLES:
            col = "review_notes" if t == "decision_trace" else (
                "resolution_notes" if t == "fraud_signals" else "notes")
            cross[t] = rc(await app.execute(
                f"UPDATE {t} SET {col}='x' WHERE application_id=$1", A0))
    results["d"] = {"pass": all(v == 1 for v in own.values())
                            and all(v == 0 for v in cross.values()),
                    "own_tenant_rowcounts": own, "cross_tenant_rowcounts": cross}

    # (e) security_invoker view enforces isolation
    async with app.transaction():
        await set_local(app, TEN)
        r1 = await app.fetchrow(
            "SELECT count(*) AS n, array_agg(DISTINCT tenant_id) AS ts "
            "FROM vw_fraud_screening_context")
    async with app.transaction():
        await set_local(app, "summit")
        r2 = await app.fetchrow(
            "SELECT count(*) AS n, array_agg(DISTINCT tenant_id) AS ts "
            "FROM vw_fraud_screening_context")
    qa_ts, sm_ts = sorted(r1["ts"] or []), sorted(r2["ts"] or [])
    results["e"] = {"pass": qa_ts == [TEN] and r1["n"] == len(APPS)
                            and sm_ts == ["summit"] and TEN not in sm_ts and r2["n"] > 0,
                    "view_as_qa_c_test": {"n": r1["n"], "tenants": qa_ts},
                    "view_as_summit": {"n": r2["n"], "tenants": sm_ts}}


async def main():
    import asyncpg
    url = os.environ["DATABASE_URL"]
    pwd = os.environ.get("ACCORD_APP_PWD")
    if not pwd:
        print("FATAL: ACCORD_APP_PWD not set"); raise SystemExit(2)

    results, error = {}, None
    admin = await asyncpg.connect(url)  # edms_admin
    try:
        # pre-clean (idempotent) + SETUP, all as edms_admin
        async with admin.transaction():
            for t in ALL_TABLES:
                await admin.execute(f"DELETE FROM {t} WHERE tenant_id=$1", TEN)
            for a in APPS:
                await admin.execute(
                    "INSERT INTO entity_states (application_id, tenant_id) VALUES ($1,$2)", a, TEN)
            await admin.execute(
                "INSERT INTO decision_trace (application_id, tenant_id, final_outcome) "
                "VALUES ($1,$2,'approve')", A0, TEN)
            await admin.execute(
                "INSERT INTO fraud_signals (application_id, tenant_id, signal_type, severity, description) "
                "VALUES ($1,$2,'other','low','qa test row')", A0, TEN)
            await admin.execute(
                "INSERT INTO loan_condition_instances "
                "(application_id, tenant_id, condition_code, category, condition_text, prior_to) "
                "VALUES ($1,$2,'QA','qa','qa test','closing')", A0, TEN)
            await admin.execute(
                "INSERT INTO property_eligibility (application_id, tenant_id) VALUES ($1,$2)", A0, TEN)
        print(f"SETUP: {len(APPS)} entity_states + 1 row each in {CHILD_TABLES} for tenant '{TEN}'")

        # CHECKS as accord_app (RLS enforced)
        app = await asyncpg.connect(url, user="accord_app", password=pwd)
        who = await app.fetchval("SELECT current_user")
        print(f"CHECKS connected as: {who}")
        try:
            await run_checks(app, results)
        except Exception as e:  # noqa: BLE001
            error = repr(e)
        finally:
            await app.close()
    except Exception as e:  # noqa: BLE001
        error = error or repr(e)
    finally:
        # CLEANUP always (as edms_admin), regardless of pass/fail
        try:
            async with admin.transaction():
                for t in ALL_TABLES:
                    await admin.execute(f"DELETE FROM {t} WHERE tenant_id=$1", TEN)
            leftover = {t: await admin.fetchval(
                f"SELECT count(*) FROM {t} WHERE tenant_id=$1", TEN) for t in ALL_TABLES}
            print("CLEANUP: leftover rows per table:", leftover)
        except Exception as e:  # noqa: BLE001
            print("CLEANUP ERROR:", repr(e))
        finally:
            await admin.close()

    # REPORT
    print("\n===== ISOLATION TEST RESULTS =====")
    labels = {
        "a": "app.tenant_id=summit  -> only summit visible, qa_c_test invisible",
        "b": "app.tenant_id=qa_c_test -> only test rows visible, summit invisible",
        "c": "app.tenant_id=accord_admin -> all tenants visible (sentinel)",
        "d": "4 UPDATE paths allowed for own tenant, denied cross-tenant",
        "e": "security_invoker view enforces isolation",
    }
    all_pass = True
    for k in ["a", "b", "c", "d", "e"]:
        r = results.get(k)
        if not r:
            print(f"[{k}] FAIL (did not run)  {labels[k]}"); all_pass = False; continue
        ok = r.pop("pass")
        all_pass = all_pass and ok
        print(f"[{k}] {'PASS' if ok else 'FAIL'}  {labels[k]}")
        print(f"      detail: {r}")
    if error:
        print("\nERROR during checks:", error); all_pass = False
    print("\nOVERALL:", "ALL PASS" if all_pass else "FAIL")
    if error:
        raise SystemExit(1)


asyncio.run(main())

# Follow-ups

Tracked so they're not lost. Add new items at the top of the relevant section.

## Conditions (CN-B, from auto-condition-generation session 2026-07-08)

- [ ] **Dashboard aggregate views → `loan_condition_instances`.** `api/accord/dashboard.py`
  reads pre-aggregated `blocking_conditions`/`open_conditions`/`overdue_conditions` from an
  aggregate table/view (not the live `vw_loan_conditions_aggregate`). The portfolio dashboard
  counts won't reflect the 45,554 auto-generated conditions until that agg source is repointed.
  (Loan-detail panel + Decision-Readiness donut already read the CN-C views correctly.)
- [ ] **~5 `${ltv}` conditions** still show a literal placeholder — their linked decision had no
  parseable `ltv` in the boundary_rule. Low priority.

## DTI surfacing (from 2026-07-08 session)

- [ ] **`entity_states.dti_back` backfill deferred (data quality).** The upstream
  `dti_calculation` `context.dti` is an **obligations-only ratio**
  (`monthly_obligations / monthly_income`) that **excludes the proposed PITI**, so it reads far
  too low (APP-SC10-004: 5.9% vs a real back-end DTI ~33%) and is inconsistent with existing
  `dti_back` values (32–88%). Backfilling would surface misleading DTIs, so we show `—` instead.
  8,742/8,912 loans have NULL/0 `dti_back` (root cause: synthetic `verified_income = 0` →
  `dti = inf`). Revisit when Capital Loans real data flows: persist
  `(PITI + monthly_obligations) / qualifying_monthly_income` to `entity_states.dti_back`.

## Security (from QA-C — RLS tenant isolation, closed 2026-06-30)

QA-C itself is **complete**: `/api/accord/*` now enforces RLS via the non-bypass
`accord_app` role (ECS task-def `accord-api:80`, env `ACCORD_DATABASE_URL`).
These are the residual, out-of-scope items deliberately deferred (Option 1 —
smallest blast radius). None block the QA-C fix.

- [ ] **Legacy surfaces still bypass RLS — DEFERRED (internal-only, accepted 2026-06-30).**
  The EDMS `/workbench` router (`ui/edms_routes.py:354`, `ui/views.py:2968`) and the
  `core/*` store pools (`core/edms_store.py:323`, `core/decision_store.py:91`,
  `core/context_store/postgres_store.py:83`, `core/audit/store.py:188`) still connect
  as `edms_admin` via `DATABASE_URL`, so RLS is bypassed there. **Decision:** these are
  internal-only, NOT part of the product surface a lender sees, so this stays deferred;
  the product API `/api/accord/*` is already RLS-enforced.

  Wiring them is a **QA-C-sized effort, NOT a quick TenantPool wrap**:
  - Wrapping in `TenantPool` alone is a **no-op for RLS** — these pools connect as
    `edms_admin` (bypassrls); they must ALSO switch to `ACCORD_DATABASE_URL` (accord_app).
  - `ui/edms_routes.py:355` runs **startup DDL** (`_ensure_stale_column` → `ALTER TABLE`)
    at pool init — as `accord_app` (non-owner) that is **denied** and 500s the pool.
    Relocate that DDL to a one-off `edms_admin` migration first.
  - Non-request paths (platform bootstrap, `core/scenarios/runner.py:57`, workers) have
    no tenant contextvar → would **fail closed (0 rows)**. Each needs an explicit
    `set_tenant('accord_admin')` sentinel.
  - Requires an isolation test + staged deploy (like QA-C Steps 4–5).

- [x] **`*_write` INSERT policies use `WITH CHECK (true)`.** — DONE 2026-07-01
  (`tighten_insert_with_check.sql`). The 16 tenant-scoped `*_write` INSERT policies
  now enforce `(tenant_id)::text = current_setting('app.tenant_id', true) OR
  = 'accord_admin'`; verified own-tenant insert succeeds and cross-tenant insert is
  rejected by RLS. `catalogue_staging_insert` intentionally left `WITH CHECK (true)`
  (shared, no `tenant_id`).

- [x] **Migrate secrets to AWS Secrets Manager.** — DONE 2026-07-01
  (`item4_secrets_manager.md`). `DATABASE_URL`, `ACCORD_DATABASE_URL`, `JWT_SECRET`
  moved to Secrets Manager (`edms/accord-api/*`, us-east-1) and injected via task-def
  `accord-api:81` `secrets`/`valueFrom`. No IAM change (execution role already covers
  `edms/*`). Verified: `/health` 200 + cross-tenant check (summit 49 / meridian 16,
  isolated). Rollback: revert service to `accord-api:80`.

- No other changes needed for QA-C.

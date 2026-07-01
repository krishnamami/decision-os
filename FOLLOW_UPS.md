# Follow-ups

Tracked so they're not lost. Add new items at the top of the relevant section.

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

- [ ] **`*_write` INSERT policies use `WITH CHECK (true)`.** Inserts are not
  tenant-constrained at the DB layer — the app supplies `tenant_id` from the JWT,
  but a compromised/buggy caller could insert rows for another tenant. Defense-in-
  depth: tighten the `*_write` INSERT policies to
  `WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))`.

- [ ] **Migrate secrets to AWS Secrets Manager.** `DATABASE_URL`,
  `ACCORD_DATABASE_URL`, and `JWT_SECRET` are plaintext environment variables in
  the `accord-api` ECS task definition (and visible via CloudTrail on
  `RegisterTaskDefinition`). Move them to Secrets Manager and reference by ARN in
  the task-def `secrets` block.

- No other changes needed for QA-C.

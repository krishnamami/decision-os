# Follow-ups

Tracked so they're not lost. Add new items at the top of the relevant section.

## Security (from QA-C — RLS tenant isolation, closed 2026-06-30)

QA-C itself is **complete**: `/api/accord/*` now enforces RLS via the non-bypass
`accord_app` role (ECS task-def `accord-api:80`, env `ACCORD_DATABASE_URL`).
These are the residual, out-of-scope items deliberately deferred (Option 1 —
smallest blast radius). None block the QA-C fix.

- [ ] **Legacy surfaces still bypass RLS.** The EDMS `/workbench` router and all
  `core/*` store pools (`core/edms_store.py`, `core/decision_store.py`,
  `core/context_store/postgres_store.py`, `core/audit/store.py`, `core/aus/store.py`,
  `core/evidence/store.py`, `core/trace/postgres_learning_store.py`) still connect
  as `edms_admin` via `DATABASE_URL`, so RLS is bypassed on those paths. If any of
  them serve real tenant data cross-tenant, that is still a gap. Fix: wrap those
  pools with the same `core/db/tenant_pool.py::TenantPool` pattern (and wire tenant
  context), OR confirm the surfaces are internal-only and document that.

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

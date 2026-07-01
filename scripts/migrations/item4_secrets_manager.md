# Item 4 — Secrets Manager migration (accord-api)

Done 2026-07-01. Moved the 3 sensitive `accord-api` env vars off plaintext ECS
task-def `environment` into AWS Secrets Manager, injected via task-def `secrets`.

## Secrets created (us-east-1, `edms/` prefix)
| ECS var | Secret name |
|---|---|
| `DATABASE_URL` | `edms/accord-api/DATABASE_URL` |
| `ACCORD_DATABASE_URL` | `edms/accord-api/ACCORD_DATABASE_URL` |
| `JWT_SECRET` | `edms/accord-api/JWT_SECRET` |

Values were copied from task-def `accord-api:80` env. To rotate: update the secret
value (`aws secretsmanager put-secret-value`) and force a new deployment.

## Task definition
- **`accord-api:81`** — the 3 vars removed from `containerDefinitions[0].environment`
  and added to `containerDefinitions[0].secrets` as `{name, valueFrom: <secret ARN>}`.
- `REDIS_URL` / `ANTHROPIC_API_KEY` remain in `environment` (empty, non-sensitive).
- No app code change — ECS injects `secrets` as env vars at container start, so
  `os.environ` sees them identically.

## IAM
- No change needed. The task has **no task role**; secrets are fetched by the
  **execution role `ecsTaskExecutionRole`**, whose inline policy `edms-secrets-access`
  already grants `secretsmanager:GetSecretValue` on
  `arn:aws:secretsmanager:us-east-1:...:secret:edms/*`. Secrets were named under
  `edms/` so they're covered. Default AWS-managed KMS key — no extra `kms:Decrypt`.

## Verification (post-deploy)
- `/health` 200, `/api/accord/health` 200.
- Cross-tenant API check PASS: summit 49 / meridian 16, disjoint, cross-tenant 404/404,
  own-loan 200 — proving all 3 secrets injected correctly (JWT sign/verify + both DB
  connections + RLS still enforced).

## Rollback
`aws ecs update-service --cluster accord --service accord-api --task-definition accord-api:80 --force-new-deployment --region us-east-1`
(reverts to the plaintext-env revision; the secrets remain and are harmless).

## Residual
The secret values still exist in the developer `.env` locally (out of scope) and
passed through the `CreateSecret`/prior `RegisterTaskDefinition` API calls (CloudTrail).
They are no longer in the live task-def `environment` plaintext.

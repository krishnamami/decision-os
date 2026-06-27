# HA-A — Multi-AZ RDS + Automated Failover

> Infrastructure spec. The AWS account (`621646470377`) is real and reachable; the
> running platform is **not yet wired** to a Multi-AZ cluster. This document is the
> target configuration + the migration/failover procedure. Apply before production GA.

---

## 1. Current Setup

The application connects through a single lazy asyncpg pool over `DATABASE_URL`
(`api/accord/pipeline.py:_get_pool`, `min_size=1, max_size=5`). There is **no failover
endpoint, no read replica, and no connection proxy** today — `DATABASE_URL` points
directly at one RDS instance (the production RDS this repo's local scripts also hit).

Resilience that already exists: `core/cron/runner.py` detects connection-level errors
(RDS idle-reaper, pgbouncer invalidation, network blip), **drops both pools and retries
the row once** (`runner.py:258-290`), and pre-emptively cycles pools every 500 rows. So
a brief failover is already survivable at the row level — see §6.

## 2. Target: Multi-AZ RDS Configuration

| Setting | Value | Rationale |
|---|---|---|
| Engine | PostgreSQL 16.x | Matches current |
| Instance class | **db.r6g.xlarge** (4 vCPU / 32 GiB) min | Memory-bound persona joins; scale to r6g.2xlarge under load |
| **Multi-AZ** | **Enabled** (synchronous standby) | Automatic failover **< 2 min** |
| Read replica | **1 async replica** (db.r6g.large) | Reporting / audit reads off the write primary |
| Storage | gp3, 200 GiB, 12k IOPS, autoscaling to 1 TiB | |
| `max_connections` | **500** (parameter group) | Headroom for ECS scale-out (HA-B: up to 10 tasks × pool) |
| `pg_stat_statements` | enabled (`shared_preload_libraries`) | Query observability (HA-E) |
| Backup retention | **7 days** automated + **35-day PITR** window | HA-D |
| Maintenance window | **Sunday 03:00–04:00 UTC** | Lowest traffic |
| Enhanced monitoring | **60-second** interval | HA-E OS-level metrics |
| Deletion protection | Enabled | |
| Encryption at rest | KMS (aws/rds) | |

## 3. Connection-String Changes

Point the app at the **cluster/failover-aware endpoint**, never an instance address:

```
# BEFORE (single instance — fails hard on failover)
DATABASE_URL=postgresql://USER:PASS@accord-prod.xxxx.us-east-1.rds.amazonaws.com:5432/accord

# AFTER (writer endpoint — survives failover automatically)
DATABASE_URL=postgresql://USER:PASS@accord-prod.cluster-xxxx.us-east-1.rds.amazonaws.com:5432/accord

# Reporting / audit reads (HA-E dashboards, examiner exports) — reader endpoint
DATABASE_URL_RO=postgresql://USER:PASS@accord-prod.cluster-ro-xxxx.us-east-1.rds.amazonaws.com:5432/accord
```

The writer endpoint's DNS CNAME flips to the promoted standby on failover; the asyncpg
pool reset in `runner.py` re-resolves it on the retry. The read endpoint is **optional**
and additive — no code reads `DATABASE_URL_RO` today; wiring reporting reads to it is a
follow-up.

## 4. Terraform Snippet

```hcl
resource "aws_db_instance" "accord_prod" {
  identifier                 = "accord-prod"
  engine                     = "postgres"
  engine_version             = "16.4"
  instance_class             = "db.r6g.xlarge"
  allocated_storage          = 200
  max_allocated_storage      = 1024
  storage_type               = "gp3"
  iops                       = 12000

  multi_az                   = true          # synchronous standby + auto-failover
  backup_retention_period    = 7             # automated daily backups
  backup_window              = "07:00-08:00" # UTC, off-peak
  maintenance_window         = "sun:03:00-sun:04:00"

  monitoring_interval        = 60            # enhanced monitoring
  monitoring_role_arn        = aws_iam_role.rds_monitoring.arn
  performance_insights_enabled = true

  parameter_group_name       = aws_db_parameter_group.accord_pg16.name
  deletion_protection        = true
  storage_encrypted          = true
  apply_immediately          = false
}

resource "aws_db_parameter_group" "accord_pg16" {
  name   = "accord-pg16"
  family = "postgres16"
  parameter { name = "max_connections"             value = "500" }
  parameter { name = "shared_preload_libraries"    value = "pg_stat_statements" }
}

# Reporting replica (async) — reads only
resource "aws_db_instance" "accord_prod_replica" {
  identifier          = "accord-prod-ro"
  replicate_source_db = aws_db_instance.accord_prod.identifier
  instance_class      = "db.r6g.large"
  multi_az            = false
}
```

## 5. Failover Time + Impact

- **Multi-AZ automatic failover:** typically **60–120 s** (DNS flip + standby promotion).
- During the window, new connections fail and in-flight statements abort.

## 6. Decision: In-Flight Decisions on Failover → Runner Retries

In-flight persona decisions are **not lost**. `runner.py` wraps each application in a
connection-error guard (`_looks_like_conn_error` → `_reset_pools()` → re-run
`_process_one` once; `runner.py:258-290`). A failover that aborts a statement looks
exactly like the RDS idle-reaper case the runner already handles:

1. Statement aborts mid-decision → caught as a connection error.
2. Both pools are dropped (forcing DNS re-resolution to the promoted writer).
3. The row is retried once after the standby is promoted.
4. If the retry still fails (failover > retry window), the app is recorded in `errors[]`
   and **re-run on the next pipeline pass** — decisions are idempotent per
   `(application_id, decision_id)`, so no double-write.

The SQS consumer path (IN-A) adds a second safety net: an un-acked message returns to the
queue and is redelivered, so a failover mid-message replays cleanly (the DLQ catches
poison messages). **No manual intervention is required for an automatic failover.**

---

*HA-A · Multi-AZ RDS spec + failover procedure. Apply via Terraform before production GA.*

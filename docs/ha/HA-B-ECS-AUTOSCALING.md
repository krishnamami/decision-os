# HA-B — ECS Service Auto-Scaling + Health Checks

> Infrastructure spec + a thin code change (`api/accord/health.py` deep-health
> endpoint). The platform runs on a dedicated `accord` ECS cluster behind an ALB.

---

## 1. Health Endpoints

Two distinct probes — a **cheap public liveness** probe for the ALB and a **deep
readiness** probe for ops. (Spec correction: making the 30-second ALB liveness check
hit the database every tick would be an anti-pattern, so the component checks live on a
separate authenticated route.)

| Endpoint | Auth | Cost | Used by |
|---|---|---|---|
| `GET /api/accord/health` | none (public) | trivial — returns `{"status":"ok"}` | **ALB target group** (every 30s) |
| `GET /api/accord/health/deep` | JWT (`get_current_user`) | one DB round-trip | ops, uptime monitors, dashboards |

**`GET /api/accord/health/deep`** (HA-B, new) returns per component:

```json
{
  "status": "ok",                       // "degraded" if the DB is unreachable
  "db_latency_ms": 12.4,                // real SELECT 1 round-trip; null if down
  "sqs_configured": false,              // IN-A graceful no-AWS
  "s3_configured": false,               // RA-P0-A graceful no-AWS
  "test_count": 1215,                   // from docs/ha/test_count.txt manifest
  "last_decision_timestamp": "2026-06-24T...Z",  // IN-C watermark
  "timestamp": "2026-06-27T...Z"
}
```

The endpoint never raises (a probe that 500s is useless) and is decision-path-inert.

## 2. ECS Task Definition

```jsonc
{
  "family": "accord-api",
  "cpu": "1024",            // 1 vCPU
  "memory": "2048",         // 2 GiB
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "containerDefinitions": [{
    "name": "accord-api",
    "portMappings": [{ "containerPort": 8000 }],
    "healthCheck": {
      "command": ["CMD-SHELL", "curl -f http://localhost:8000/api/accord/health || exit 1"],
      "interval": 30, "timeout": 5, "retries": 3, "startPeriod": 60
    }
  }]
}
```

## 3. Auto-Scaling Policy (target tracking)

| Policy | Setting |
|---|---|
| Metric | ECS service average **CPU 70%** (target tracking) |
| Scale-out | **+2 tasks** when CPU > 70% sustained **2 min** |
| Scale-in | **−1 task** when CPU < 30% sustained **10 min** (conservative) |
| Min tasks | **2** (always multi-task for AZ resilience) |
| Max tasks | **10** (bounded by RDS `max_connections=500`, HA-A) |

```hcl
resource "aws_appautoscaling_target" "accord" {
  service_namespace  = "ecs"
  resource_id        = "service/accord/accord-api"
  scalable_dimension = "ecs:service:DesiredCount"
  min_capacity       = 2
  max_capacity       = 10
}
resource "aws_appautoscaling_policy" "cpu" {
  name               = "accord-cpu-target"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.accord.resource_id
  scalable_dimension = aws_appautoscaling_target.accord.scalable_dimension
  service_namespace  = "ecs"
  target_tracking_scaling_policy_configuration {
    target_value       = 70.0
    predefined_metric_specification { predefined_metric_type = "ECSServiceAverageCPUUtilization" }
    scale_out_cooldown = 120
    scale_in_cooldown  = 600
  }
}
```

## 4. ALB Target Group Health Check

| Setting | Value |
|---|---|
| Path | `/api/accord/health` (the cheap public probe) |
| Interval | 30s · Timeout 5s · Healthy 2 · Unhealthy **3** |
| **Deregistration delay** | **30s** — let in-flight decisions drain before a task is killed |

## 5. Rolling Deployment

| Setting | Value | Effect |
|---|---|---|
| Minimum healthy % | **50** | At least 1 of 2 tasks always serving |
| Maximum % | **200** | New tasks come up before old drain |
| Circuit breaker | enabled, **rollback on failed deploy** | |

Combined with the 30s deregistration delay, a deploy drains in-flight requests instead
of dropping them. Idempotent decisions (per `application_id, decision_id`) mean a request
interrupted mid-deploy is safely re-run.

---

*HA-B · ECS auto-scaling spec + `GET /api/accord/health/deep`.*

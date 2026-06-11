#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Accord — build, push, and deploy the API + frontend to ECS Fargate.
#
#   bash deploy/deploy.sh
#
# Prereqs: docker, aws CLI (configured), and a .env at the repo root holding
# DATABASE_URL / JWT_SECRET / REDIS_URL / ANTHROPIC_API_KEY. Infrastructure
# (cluster, ALB, target groups, SG, subnets, ECR repos) is assumed to exist.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── AWS resource values ──────────────────────────────────────────────────────
AWS_ACCOUNT=621646470377
REGION=us-east-1
CLUSTER=accord
SUBNET_1=subnet-06f6695e50577d0a6
SUBNET_2=subnet-0c752ca6465821670
TASK_SG=sg-0f1a63688a8bfad05
API_TG_ARN=arn:aws:elasticloadbalancing:us-east-1:621646470377:targetgroup/accord-api-tg/a61aaa03b2046233
FRONTEND_TG_ARN=arn:aws:elasticloadbalancing:us-east-1:621646470377:targetgroup/accord-frontend-tg/f2b7aaeb15853919
ECR_API=621646470377.dkr.ecr.us-east-1.amazonaws.com/accord-api
ECR_FRONTEND=621646470377.dkr.ecr.us-east-1.amazonaws.com/accord-frontend
REGISTRY=621646470377.dkr.ecr.us-east-1.amazonaws.com
ALB_DNS=accord-alb-588286075.us-east-1.elb.amazonaws.com

NETWORK_CFG="awsvpcConfiguration={subnets=[$SUBNET_1,$SUBNET_2],securityGroups=[$TASK_SG],assignPublicIp=ENABLED}"

# ── Locate repo root + load secrets ──────────────────────────────────────────
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then echo "ERROR: .env not found at repo root."; exit 1; fi
set -a; source .env; set +a
: "${DATABASE_URL:?DATABASE_URL missing from .env}"
: "${JWT_SECRET:?JWT_SECRET missing from .env}"
export REDIS_URL="${REDIS_URL:-}"
export ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-}"

PYTHON="$(command -v python3 || command -v python)"
[[ -n "$PYTHON" ]] || { echo "ERROR: python not found (needed to render the task definition)."; exit 1; }

# ── a) ECR login ─────────────────────────────────────────────────────────────
echo "==> [a] Logging in to ECR"
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$REGISTRY"

# ── b) Build + push API image (amd64 — Fargate runs X86_64) ───────────────────
echo "==> [b] Building + pushing API image"
docker build --platform linux/amd64 -t "$ECR_API:latest" -f Dockerfile .
docker push "$ECR_API:latest"

# ── c) Build + push frontend image ───────────────────────────────────────────
echo "==> [c] Building + pushing frontend image"
docker build --platform linux/amd64 --build-arg VITE_API_URL= -t "$ECR_FRONTEND:latest" -f frontend/Dockerfile frontend
docker push "$ECR_FRONTEND:latest"

# ── d) Register task definitions ─────────────────────────────────────────────
echo "==> [d] Ensuring CloudWatch log groups"
for lg in /ecs/accord-api /ecs/accord-frontend; do
  aws logs create-log-group --log-group-name "$lg" --region "$REGION" >/dev/null 2>&1 || true
done

echo "==> [d] Registering task definitions"
# Fill ${VAR} placeholders in the API task def from the environment. Using the
# JSON module guarantees values are escaped correctly even if a secret contains
# quotes or backslashes — and keeps the rendered file (with secrets) out of git.
RENDERED_API="$(mktemp)"
trap 'rm -f "$RENDERED_API"' EXIT
"$PYTHON" - deploy/ecs-api-task.json > "$RENDERED_API" <<'PY'
import json, os, sys
td = json.load(open(sys.argv[1]))
for c in td["containerDefinitions"]:
    for e in c.get("environment", []):
        v = e["value"]
        if v.startswith("${") and v.endswith("}"):
            e["value"] = os.environ.get(v[2:-1], "")
json.dump(td, sys.stdout)
PY

API_TD=$(aws ecs register-task-definition --cli-input-json "file://$RENDERED_API" \
  --region "$REGION" --query 'taskDefinition.taskDefinitionArn' --output text)
echo "    API task def:      $API_TD"

FRONTEND_TD=$(aws ecs register-task-definition --cli-input-json file://deploy/ecs-frontend-task.json \
  --region "$REGION" --query 'taskDefinition.taskDefinitionArn' --output text)
echo "    Frontend task def: $FRONTEND_TD"

# ── e) Create or update the services ─────────────────────────────────────────
deploy_service () {
  local name=$1 task_def=$2 tg_arn=$3 container=$4 port=$5
  local status
  status=$(aws ecs describe-services --cluster "$CLUSTER" --services "$name" --region "$REGION" \
            --query 'services[0].status' --output text 2>/dev/null || echo "MISSING")

  if [[ "$status" == "ACTIVE" ]]; then
    echo "==> [e] Updating service $name"
    aws ecs update-service --cluster "$CLUSTER" --service "$name" \
      --task-definition "$task_def" --force-new-deployment --region "$REGION" >/dev/null
  else
    echo "==> [e] Creating service $name"
    aws ecs create-service --cluster "$CLUSTER" --service-name "$name" \
      --task-definition "$task_def" --desired-count 1 --launch-type FARGATE \
      --network-configuration "$NETWORK_CFG" \
      --load-balancers "targetGroupArn=$tg_arn,containerName=$container,containerPort=$port" \
      --health-check-grace-period-seconds 60 --region "$REGION" >/dev/null
  fi
}

deploy_service accord-api      "$API_TD"      "$API_TG_ARN"      accord-api      8000
deploy_service accord-frontend "$FRONTEND_TD" "$FRONTEND_TG_ARN" accord-frontend 80

# ── f) Wait for the services to stabilize ────────────────────────────────────
echo "==> [f] Waiting for services to stabilize (a few minutes)…"
aws ecs wait services-stable --cluster "$CLUSTER" --services accord-api accord-frontend --region "$REGION"

# ── g) Done ──────────────────────────────────────────────────────────────────
echo ""
echo "==> [g] Deployed."
echo "    Access: http://$ALB_DNS"

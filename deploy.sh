#!/bin/bash
# Accord — Manual ECS Deploy Script
# Deploys frontend and/or API to ECS after a git push
#
# Usage:
#   ./deploy.sh           — deploy both frontend + API
#   ./deploy.sh frontend  — deploy frontend only
#   ./deploy.sh api       — deploy API only
#
# Prerequisites:
#   aws cli configured (aws sts get-caller-identity should return account 621646470377)
#   docker running
#   .env file at repo root with ANTHROPIC_API_KEY etc.

set -e

# ── Config ────────────────────────────────────────────────────────────────────
AWS_ACCOUNT="621646470377"
AWS_REGION="us-east-1"
ECS_CLUSTER="accord"
ECR_API="$AWS_ACCOUNT.dkr.ecr.$AWS_REGION.amazonaws.com/accord-api"
ECR_FRONTEND="$AWS_ACCOUNT.dkr.ecr.$AWS_REGION.amazonaws.com/accord-frontend"
ECS_SERVICE_API="accord-api"
ECS_SERVICE_FRONTEND="accord-frontend"

TARGET=$1  # "frontend", "api", or empty (both)

echo "=== Accord Deploy ==="
echo "Cluster:  $ECS_CLUSTER"
echo "Region:   $AWS_REGION"
echo "Target:   ${TARGET:-both}"
echo ""

# ── ECR Login ────────────────────────────────────────────────────────────────
echo ">>> ECR login..."
aws ecr get-login-password --region $AWS_REGION \
  | docker login --username AWS --password-stdin \
    "$AWS_ACCOUNT.dkr.ecr.$AWS_REGION.amazonaws.com"

# ── Deploy Frontend ───────────────────────────────────────────────────────────
deploy_frontend() {
  echo ""
  echo ">>> Building frontend..."
  cd frontend
  docker build -t accord-frontend .
  docker tag accord-frontend:latest "$ECR_FRONTEND:latest"
  echo ">>> Pushing frontend image..."
  docker push "$ECR_FRONTEND:latest"
  cd ..

  echo ">>> Deploying frontend ECS service..."
  aws ecs update-service \
    --cluster $ECS_CLUSTER \
    --service $ECS_SERVICE_FRONTEND \
    --force-new-deployment \
    --region $AWS_REGION \
    --output text --query 'service.serviceName'

  echo ">>> Waiting for frontend to stabilize..."
  aws ecs wait services-stable \
    --cluster $ECS_CLUSTER \
    --services $ECS_SERVICE_FRONTEND \
    --region $AWS_REGION
  echo "    Frontend stable ✓"
}

# ── Deploy API ────────────────────────────────────────────────────────────────
deploy_api() {
  echo ""
  echo ">>> Building API..."
  docker build -t accord-api .
  docker tag accord-api:latest "$ECR_API:latest"
  echo ">>> Pushing API image..."
  docker push "$ECR_API:latest"

  echo ">>> Deploying API ECS service..."
  aws ecs update-service \
    --cluster $ECS_CLUSTER \
    --service $ECS_SERVICE_API \
    --force-new-deployment \
    --region $AWS_REGION \
    --output text --query 'service.serviceName'

  echo ">>> Waiting for API to stabilize..."
  aws ecs wait services-stable \
    --cluster $ECS_CLUSTER \
    --services $ECS_SERVICE_API \
    --region $AWS_REGION
  echo "    API stable ✓"
}

# ── Run ───────────────────────────────────────────────────────────────────────
case "$TARGET" in
  frontend) deploy_frontend ;;
  api)      deploy_api ;;
  *)        deploy_frontend; deploy_api ;;
esac

echo ""
echo "=== Deploy complete ==="
echo "Live at: http://accord-alb-588286075.us-east-1.elb.amazonaws.com"

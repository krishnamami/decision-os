#!/usr/bin/env bash
# Build, push, and roll out the Accord images to AWS ECR + ECS.
#
# Prerequisites (create once, before the first run):
#   - ECR repos:           accord-api, accord-frontend
#   - ECS cluster:         accord  (or reuse the existing EDMS cluster)
#   - ECS services:        accord-api, accord-frontend (with task definitions)
#   - ALB + target groups: /api/* → api service, /* → frontend service
#   - Security groups:     allow HTTP/HTTPS (80/443) in, RDS/Redis out
#
# The frontend image calls /api/ on its own origin, so the ALB must route
# /api/* to the api target group and everything else to the frontend.
#
# Usage:  ./scripts/deploy.sh
set -euo pipefail

AWS_REGION="${AWS_REGION:-us-east-1}"
ECR_REPO="${ECR_REPO:-accord}"
ECS_CLUSTER="${ECS_CLUSTER:-accord}"

AWS_ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

echo "==> Logging in to ECR (${REGISTRY})"
aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "$REGISTRY"

echo "==> Building + pushing API image"
docker build -t accord-api .
docker tag accord-api:latest "${REGISTRY}/${ECR_REPO}-api:latest"
docker push "${REGISTRY}/${ECR_REPO}-api:latest"

echo "==> Building + pushing frontend image"
docker build -t accord-frontend ./frontend
docker tag accord-frontend:latest "${REGISTRY}/${ECR_REPO}-frontend:latest"
docker push "${REGISTRY}/${ECR_REPO}-frontend:latest"

echo "==> Forcing new ECS deployments"
aws ecs update-service --cluster "$ECS_CLUSTER" --service accord-api --force-new-deployment >/dev/null
aws ecs update-service --cluster "$ECS_CLUSTER" --service accord-frontend --force-new-deployment >/dev/null

echo "Deployed. Watch rollout with:"
echo "  aws ecs wait services-stable --cluster ${ECS_CLUSTER} --services accord-api accord-frontend"

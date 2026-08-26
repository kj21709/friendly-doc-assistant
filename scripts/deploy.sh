#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STACK_NAME="${1:-friendly-doc-assistant}"
AWS_REGION="${AWS_REGION:-us-east-1}"
LLM_MODEL_OVERRIDE="${2:-${LLM_MODEL_ID:-}}"

cd "$PROJECT_DIR"
sam build --use-container

DEPLOY_ARGS=(
  --stack-name "$STACK_NAME"
  --region "$AWS_REGION"
  --resolve-s3
  --capabilities CAPABILITY_IAM
  --confirm-changeset
)
if [[ -n "$LLM_MODEL_OVERRIDE" ]]; then
  DEPLOY_ARGS+=(
    --parameter-overrides
    "ParameterKey=LlmModelId,ParameterValue=$LLM_MODEL_OVERRIDE"
  )
fi
sam deploy "${DEPLOY_ARGS[@]}"

API_URL="$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" --region "$AWS_REGION" --query "Stacks[0].Outputs[?OutputKey=='ApiUrl'].OutputValue" --output text)"
SITE_BUCKET="$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" --region "$AWS_REGION" --query "Stacks[0].Outputs[?OutputKey=='WebsiteBucketName'].OutputValue" --output text)"
DISTRIBUTION_ID="$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" --region "$AWS_REGION" --query "Stacks[0].Outputs[?OutputKey=='DistributionId'].OutputValue" --output text)"
SITE_URL="$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" --region "$AWS_REGION" --query "Stacks[0].Outputs[?OutputKey=='WebsiteUrl'].OutputValue" --output text)"

STAGE_DIR="$(mktemp -d)"
trap 'rm -rf "$STAGE_DIR"' EXIT
cp -R frontend/. "$STAGE_DIR/"
sed "s|__API_URL__|$API_URL|g" frontend/config.js > "$STAGE_DIR/config.js"
aws s3 sync "$STAGE_DIR" "s3://$SITE_BUCKET" --delete --region "$AWS_REGION"
aws cloudfront create-invalidation --distribution-id "$DISTRIBUTION_ID" --paths '/*' >/dev/null

echo "Deployment complete: $SITE_URL"

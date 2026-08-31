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

"$PROJECT_DIR/scripts/publish-frontend.sh" "$STACK_NAME" "$AWS_REGION"

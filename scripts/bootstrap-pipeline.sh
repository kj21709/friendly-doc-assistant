#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BOOTSTRAP_STACK_NAME="${BOOTSTRAP_STACK_NAME:-friendly-doc-assistant-cicd-bootstrap}"
AWS_REGION="${AWS_REGION:-us-east-1}"
CREATE_GITHUB_OIDC_PROVIDER="${CREATE_GITHUB_OIDC_PROVIDER:-false}"

case "$CREATE_GITHUB_OIDC_PROVIDER" in
  true|false) ;;
  *)
    echo "CREATE_GITHUB_OIDC_PROVIDER must be true or false." >&2
    exit 2
    ;;
esac

cd "$PROJECT_DIR"

aws cloudformation deploy \
  --template-file infrastructure/pipeline-bootstrap.yaml \
  --stack-name "$BOOTSTRAP_STACK_NAME" \
  --capabilities CAPABILITY_NAMED_IAM \
  --region "$AWS_REGION" \
  --no-fail-on-empty-changeset \
  --parameter-overrides \
    CreateGitHubOidcProvider="$CREATE_GITHUB_OIDC_PROVIDER"

aws cloudformation update-termination-protection \
  --enable-termination-protection \
  --stack-name "$BOOTSTRAP_STACK_NAME" \
  --region "$AWS_REGION"

echo "Bootstrap stack outputs:"
aws cloudformation describe-stacks \
  --stack-name "$BOOTSTRAP_STACK_NAME" \
  --region "$AWS_REGION" \
  --query 'Stacks[0].Outputs[].{Name:OutputKey,Value:OutputValue}' \
  --output table

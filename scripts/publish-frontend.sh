#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "Usage: $0 <stack-name> <aws-region>" >&2
  exit 2
fi

STACK_NAME="$1"
AWS_REGION="$2"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

stack_output() {
  aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region "$AWS_REGION" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" \
    --output text
}

API_URL="$(stack_output ApiUrl)"
SITE_BUCKET="$(stack_output WebsiteBucketName)"
DISTRIBUTION_ID="$(stack_output DistributionId)"
SITE_URL="$(stack_output WebsiteUrl)"

for value_name in API_URL SITE_BUCKET DISTRIBUTION_ID SITE_URL; do
  value="${!value_name}"
  if [[ -z "$value" || "$value" == "None" ]]; then
    echo "Stack output $value_name is missing from $STACK_NAME." >&2
    exit 1
  fi
done

STAGE_DIR="$(mktemp -d)"
trap 'rm -rf "$STAGE_DIR"' EXIT
cp -R "$PROJECT_DIR/frontend/." "$STAGE_DIR/"
sed "s|__API_URL__|$API_URL|g" "$PROJECT_DIR/frontend/config.js" > "$STAGE_DIR/config.js"

aws s3 sync "$STAGE_DIR" "s3://$SITE_BUCKET" --delete --region "$AWS_REGION"
aws cloudfront create-invalidation \
  --distribution-id "$DISTRIBUTION_ID" \
  --paths '/*' \
  --query 'Invalidation.Id' \
  --output text

echo "Frontend published: $SITE_URL"

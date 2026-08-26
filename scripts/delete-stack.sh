#!/usr/bin/env bash
set -euo pipefail
STACK_NAME="${1:-friendly-doc-assistant}"
AWS_REGION="${AWS_REGION:-us-east-1}"

for OUTPUT in WebsiteBucketName DocumentBucketName; do
  BUCKET="$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" --region "$AWS_REGION" --query "Stacks[0].Outputs[?OutputKey=='$OUTPUT'].OutputValue" --output text)"
  if [[ -n "$BUCKET" && "$BUCKET" != "None" ]]; then
    while true; do
      VERSIONS="$(aws s3api list-object-versions --bucket "$BUCKET" --region "$AWS_REGION" --max-items 500 --query '{Objects: Versions[].{Key:Key,VersionId:VersionId}, Quiet: `true`}' --output json)"
      [[ "$VERSIONS" == *'"Key"'* ]] || break
      aws s3api delete-objects --bucket "$BUCKET" --region "$AWS_REGION" --delete "$VERSIONS" >/dev/null
    done
    while true; do
      MARKERS="$(aws s3api list-object-versions --bucket "$BUCKET" --region "$AWS_REGION" --max-items 500 --query '{Objects: DeleteMarkers[].{Key:Key,VersionId:VersionId}, Quiet: `true`}' --output json)"
      [[ "$MARKERS" == *'"Key"'* ]] || break
      aws s3api delete-objects --bucket "$BUCKET" --region "$AWS_REGION" --delete "$MARKERS" >/dev/null
    done
  fi
done
aws cloudformation delete-stack --stack-name "$STACK_NAME" --region "$AWS_REGION"
aws cloudformation wait stack-delete-complete --stack-name "$STACK_NAME" --region "$AWS_REGION"

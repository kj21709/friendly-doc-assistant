#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <api-url>" >&2
  exit 2
fi

API_URL="${1%/}"
if [[ -z "$API_URL" || "$API_URL" == "None" ]]; then
  echo "A valid API URL is required." >&2
  exit 1
fi

RESPONSE_FILE="$(mktemp)"
trap 'rm -f "$RESPONSE_FILE"' EXIT

HTTP_STATUS=$(curl \
  --silent \
  --show-error \
  --output "$RESPONSE_FILE" \
  --write-out '%{http_code}' \
  --retry 5 \
  --retry-all-errors \
  --retry-delay 3 \
  --max-time 30 \
  --get \
  --data-urlencode 'userId=PIPELINE TEST' \
  "$API_URL/documents")

if [[ "$HTTP_STATUS" != "200" ]]; then
  echo "Smoke test failed with HTTP $HTTP_STATUS:" >&2
  sed -n '1,40p' "$RESPONSE_FILE" >&2
  exit 1
fi

python3 - "$RESPONSE_FILE" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as response_file:
    payload = json.load(response_file)
if not isinstance(payload.get("documents"), list):
    raise SystemExit("Smoke test response does not contain a documents list.")
print("API smoke test passed.")
PY

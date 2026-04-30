#!/usr/bin/env bash
# End-to-end smoke test of the public API.
#
# Usage:
#   ./scripts/upload_test.sh [path/to/document.txt]
#
# Defaults to samples/short_article.txt if no path is given.
#
# Reads API_BASE_URL and API_KEY from .env (or from the environment).
# After `cdk deploy`, populate .env from stack outputs:
#   - ApiBaseUrl   → API_BASE_URL
#   - ApiKeyId     → fetch with: aws apigateway get-api-key --api-key <id> --include-value
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DOC="${1:-$REPO_ROOT/samples/short_article.txt}"

if [ ! -f "$DOC" ]; then
  echo "error: document not found: $DOC" >&2
  exit 1
fi

# Load .env if present.
if [ -f "$REPO_ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$REPO_ROOT/.env"
  set +a
fi

: "${API_BASE_URL:?API_BASE_URL is unset (set in .env or environment)}"
: "${API_KEY:?API_KEY is unset (set in .env or environment)}"

# Strip any trailing slash so we can build URLs predictably.
API_BASE_URL="${API_BASE_URL%/}"

echo "==> Requesting upload URL from $API_BASE_URL"
FILENAME="$(basename "$DOC")"
RESPONSE=$(curl -fsS -X POST "$API_BASE_URL/uploads" \
  -H "Content-Type: application/json" \
  -H "x-api-key: $API_KEY" \
  -d "{\"filename\":\"$FILENAME\"}")

SUMMARY_ID=$(echo "$RESPONSE" | python3 -c 'import json,sys; print(json.load(sys.stdin)["summary_id"])')
UPLOAD_URL=$(echo "$RESPONSE" | python3 -c 'import json,sys; print(json.load(sys.stdin)["upload_url"])')
echo "    summary_id=$SUMMARY_ID"

echo "==> Uploading $DOC to presigned URL"
curl -fsS -X PUT --upload-file "$DOC" "$UPLOAD_URL"
echo

echo "==> Polling GET /summaries/$SUMMARY_ID"
for i in $(seq 1 30); do
  POLL=$(curl -fsS "$API_BASE_URL/summaries/$SUMMARY_ID" -H "x-api-key: $API_KEY")
  STATUS=$(echo "$POLL" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("status","?"))')
  echo "    [$i] status=$STATUS"
  case "$STATUS" in
    DONE)
      echo
      echo "──────────── Summary ────────────"
      echo "$POLL" | python3 -c 'import json,sys; print(json.load(sys.stdin)["summary"])'
      echo "─────────────────────────────────"
      MODEL=$(echo "$POLL" | python3 -c 'import json,sys; print(json.load(sys.stdin)["model_id"])')
      IT=$(echo "$POLL" | python3 -c 'import json,sys; print(json.load(sys.stdin)["input_tokens"])')
      OT=$(echo "$POLL" | python3 -c 'import json,sys; print(json.load(sys.stdin)["output_tokens"])')
      echo "model=$MODEL  input_tokens=$IT  output_tokens=$OT"
      exit 0
      ;;
    FAILED)
      echo "$POLL" | python3 -m json.tool
      exit 1
      ;;
  esac
  sleep 2
done

echo "timed out waiting for DONE" >&2
exit 1

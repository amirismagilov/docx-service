#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8080}"
TOKEN="${BEARER_TOKEN:-dev-v1-token}"
DOC_ID="${DOC_ID:-}"
VERSION_ID="${VERSION_ID:-}"

if [[ -z "$DOC_ID" || -z "$VERSION_ID" ]]; then
  echo "DOC_ID and VERSION_ID are required"
  exit 1
fi

echo "1) Health check"
curl -fsS "${BASE_URL}/health" >/dev/null

echo "2) Sync generation canary"
curl -fsS -X POST "${BASE_URL}/api/v1/generations/sync" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -H "X-Request-Id: canary-sync-$(date +%s)" \
  -d "{\"documentId\":\"${DOC_ID}\",\"versionId\":\"${VERSION_ID}\",\"payload\":{\"field_1\":\"canary\"}}" \
  -o /tmp/docx-canary-sync.docx

echo "3) Async generation canary"
JOB_ID="$(
  curl -fsS -X POST "${BASE_URL}/api/v1/generations/async" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Content-Type: application/json" \
    -H "X-Request-Id: canary-async-$(date +%s)" \
    -d "{\"documentId\":\"${DOC_ID}\",\"versionId\":\"${VERSION_ID}\",\"payload\":{\"field_1\":\"canary-async\"}}" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["jobId"])'
)"

echo "4) Poll async job status"
for _ in $(seq 1 25); do
  STATUS="$(
    curl -fsS "${BASE_URL}/api/v1/generations/${JOB_ID}" \
      -H "Authorization: Bearer ${TOKEN}" \
      | python3 -c 'import json,sys; print(json.load(sys.stdin)["status"])'
  )"
  if [[ "$STATUS" == "succeeded" ]]; then
    break
  fi
  if [[ "$STATUS" == "failed" ]]; then
    echo "Async canary failed"
    exit 1
  fi
  sleep 0.3
done

echo "5) Fetch async result"
curl -fsS "${BASE_URL}/api/v1/generations/${JOB_ID}/result" \
  -H "Authorization: Bearer ${TOKEN}" \
  -o /tmp/docx-canary-async.docx

echo "Canary smoke passed"

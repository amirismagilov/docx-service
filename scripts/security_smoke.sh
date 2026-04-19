#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8080}"
TOKEN="${BEARER_TOKEN:-dev-v1-token}"
LARGE_PAYLOAD_SIZE="${LARGE_PAYLOAD_SIZE:-1200000}"

echo "1) Health endpoint"
curl -fsS "${BASE_URL}/health" >/dev/null

echo "2) Unauthorized access should be rejected (401)"
UNAUTH_STATUS="$(
  curl -s -o /tmp/docx-security-unauth.json -w '%{http_code}' \
    -X POST "${BASE_URL}/api/v1/generations/sync" \
    -H "Content-Type: application/json" \
    -d '{"documentId":"00000000-0000-0000-0000-000000000000","payload":{"field_1":"x"}}'
)"
if [[ "${UNAUTH_STATUS}" != "401" ]]; then
  echo "Expected 401 for unauthorized call, got ${UNAUTH_STATUS}"
  cat /tmp/docx-security-unauth.json || true
  exit 1
fi

echo "3) Oversized request should be rejected (413)"
python3 - <<'PY' "${LARGE_PAYLOAD_SIZE}" >/tmp/docx-security-oversized.json
import json
import sys

payload_size = int(sys.argv[1])
print(
    json.dumps(
        {
            "documentId": "00000000-0000-0000-0000-000000000000",
            "payload": {"blob": "x" * payload_size},
        }
    )
)
PY
OVERSIZED_STATUS="$(
  curl -s -o /tmp/docx-security-oversized-response.json -w '%{http_code}' \
    -X POST "${BASE_URL}/api/v1/generations/sync" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Content-Type: application/json" \
    --data-binary @/tmp/docx-security-oversized.json
)"
if [[ "${OVERSIZED_STATUS}" != "413" ]]; then
  echo "Expected 413 for oversized request, got ${OVERSIZED_STATUS}"
  cat /tmp/docx-security-oversized-response.json || true
  exit 1
fi

echo "4) Rate-limit should trigger on repeated requests (429)"
FIRST_STATUS="$(
  curl -s -o /tmp/docx-security-rate-1.json -w '%{http_code}' \
    "${BASE_URL}/api/v1/documents/00000000-0000-0000-0000-000000000000/statistics" \
    -H "Authorization: Bearer ${TOKEN}"
)"
SECOND_STATUS="$(
  curl -s -o /tmp/docx-security-rate-2.json -w '%{http_code}' \
    "${BASE_URL}/api/v1/documents/00000000-0000-0000-0000-000000000000/statistics" \
    -H "Authorization: Bearer ${TOKEN}"
)"
if [[ "${FIRST_STATUS}" != "200" && "${FIRST_STATUS}" != "404" ]]; then
  echo "Unexpected first status for rate-limit probe: ${FIRST_STATUS}"
  cat /tmp/docx-security-rate-1.json || true
  exit 1
fi
if [[ "${SECOND_STATUS}" != "429" ]]; then
  echo "Expected second status 429, got ${SECOND_STATUS}"
  cat /tmp/docx-security-rate-2.json || true
  exit 1
fi

echo "Security smoke passed"

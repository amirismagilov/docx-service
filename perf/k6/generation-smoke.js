import http from 'k6/http'
import { check, sleep } from 'k6'

const BASE_URL = __ENV.BASE_URL || 'http://127.0.0.1:8080'
const DOC_ID = __ENV.DOC_ID
const VERSION_ID = __ENV.VERSION_ID
const TOKEN = __ENV.BEARER_TOKEN || 'dev-v1-token'

export const options = {
  vus: 5,
  duration: '2m',
  thresholds: {
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(95)<1000'],
  },
}

if (!DOC_ID || !VERSION_ID) {
  throw new Error('DOC_ID and VERSION_ID must be provided')
}

export default function () {
  const payload = JSON.stringify({
    documentId: DOC_ID,
    versionId: VERSION_ID,
    payload: {
      field_1: 'value',
      timestamp: new Date().toISOString(),
    },
  })
  const res = http.post(`${BASE_URL}/api/v1/generations/sync`, payload, {
    headers: {
      Authorization: `Bearer ${TOKEN}`,
      'Content-Type': 'application/json',
      'X-Request-Id': `k6-sync-${__VU}-${__ITER}`,
    },
    timeout: '30s',
  })
  check(res, {
    'sync status is 200': (r) => r.status === 200,
    'sync returns docx content-type': (r) =>
      (r.headers['Content-Type'] || '').includes(
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
      ),
  })
  sleep(0.2)
}

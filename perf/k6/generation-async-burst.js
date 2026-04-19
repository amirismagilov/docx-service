import http from 'k6/http'
import { check, sleep } from 'k6'

const BASE_URL = __ENV.BASE_URL || 'http://127.0.0.1:8080'
const DOC_ID = __ENV.DOC_ID
const VERSION_ID = __ENV.VERSION_ID
const TOKEN = __ENV.BEARER_TOKEN || 'dev-v1-token'

export const options = {
  scenarios: {
    burst_async: {
      executor: 'ramping-arrival-rate',
      startRate: 5,
      timeUnit: '1s',
      preAllocatedVUs: 20,
      maxVUs: 60,
      stages: [
        { target: 20, duration: '30s' },
        { target: 40, duration: '1m' },
        { target: 10, duration: '30s' },
      ],
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.02'],
    http_req_duration: ['p(95)<1500'],
  },
}

if (!DOC_ID || !VERSION_ID) {
  throw new Error('DOC_ID and VERSION_ID must be provided')
}

function pollStatus(jobId) {
  for (let i = 0; i < 20; i++) {
    const statusRes = http.get(`${BASE_URL}/api/v1/generations/${jobId}`, {
      headers: { Authorization: `Bearer ${TOKEN}` },
      timeout: '10s',
    })
    if (statusRes.status !== 200) {
      return { ok: false }
    }
    const body = statusRes.json()
    if (body.status === 'succeeded') {
      return { ok: true, status: body.status }
    }
    if (body.status === 'failed') {
      return { ok: false, status: body.status }
    }
    sleep(0.2)
  }
  return { ok: false, status: 'timeout' }
}

export default function () {
  const submit = http.post(
    `${BASE_URL}/api/v1/generations/async`,
    JSON.stringify({
      documentId: DOC_ID,
      versionId: VERSION_ID,
      payload: { field_1: `user-${__VU}-${__ITER}` },
    }),
    {
      headers: {
        Authorization: `Bearer ${TOKEN}`,
        'Content-Type': 'application/json',
        'X-Request-Id': `k6-async-${__VU}-${__ITER}`,
      },
      timeout: '15s',
    }
  )
  check(submit, { 'async accepted': (r) => r.status === 202 })
  if (submit.status !== 202) {
    return
  }
  const jobId = submit.json('jobId')
  const polled = pollStatus(jobId)
  check(polled, { 'async completes': (s) => s.ok === true })
}

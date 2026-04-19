# Canary Rollout Checklist v1

## Preconditions
- Production config prepared (`DOCX_SERVICE_GENERATION_STORE`, auth token, limits).
- At least one published template version for smoke checks.
- Observability endpoint `/metrics` reachable by monitoring stack.

## Rollout Steps
1. Deploy new release to canary instance/group (5-10% traffic).
2. Run `scripts/canary_smoke.sh` against canary.
3. Check key metrics for 15-30 minutes:
   - `docx_v1_http_requests_total` by status code.
   - `docx_generation_total` success/failure.
   - `docx_generation_duration_seconds` p95 trend.
   - `docx_async_queue_depth` stability.
4. Verify business logs:
   - no spike of `http_422`/`http_429` anomalies,
   - no `generation_error` increase.
5. Validate `/api/v1/documents/{id}/statistics` returns expected counters.
6. Increase traffic stepwise (25% -> 50% -> 100%) with observation window.

## Abort Criteria
- 5xx error rate above agreed SLO threshold.
- Async queue depth continuously rising.
- Generation success rate drops below baseline.
- Canary smoke fails in sync or async path.

## Rollback Plan
1. Route traffic back to previous stable version.
2. Keep canary isolated for diagnostics.
3. Capture request IDs and error samples.
4. Open incident and root-cause ticket before next rollout.

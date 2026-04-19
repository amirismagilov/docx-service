# Analytics and Audit Model (v1)

## Goals
- Track who generated which document, when, with what input shape, and with what result.
- Provide operational and business statistics per document/template/version/client.
- Ensure security and compliance auditability without leaking sensitive payload data.

## Event Taxonomy

### Generation lifecycle events
- `generation.requested`
- `generation.queued`
- `generation.started`
- `generation.completed`
- `generation.failed`
- `generation.expired`
- `generation.result_downloaded`

### Template governance events
- `document.created`
- `document.updated`
- `version.created`
- `version.published`
- `conditional_block.created|updated|deleted`
- `signature_slot.created|updated|deleted`

### Security events
- `auth.failed`
- `authz.denied`
- `rate_limit.exceeded`
- `payload.validation_failed`
- `upload.rejected`

## Data Entities

### generation_requests
- `id` (uuid)
- `document_id` (uuid)
- `version_id` (uuid)
- `client_id` (uuid)
- `request_id` (string, correlation)
- `idempotency_key` (string, nullable)
- `mode` (`sync` | `async`)
- `payload_masked_json` (jsonb)
- `payload_hash_sha256` (string)
- `status` (`queued` | `running` | `succeeded` | `failed` | `expired`)
- `error_code` / `error_message` (nullable)
- `created_at_utc` / `started_at_utc` / `finished_at_utc`
- `latency_ms` / `queue_wait_ms` (nullable)

### generation_results
- `id` (uuid)
- `generation_request_id` (uuid)
- `storage_uri` (string)
- `file_name` (string)
- `mime_type` (string)
- `size_bytes` (bigint)
- `sha256` (string)
- `retention_until_utc`
- `created_at_utc`

### audit_events
- `id` (uuid)
- `event_type` (string)
- `severity` (`info` | `warn` | `error` | `security`)
- `actor_type` (`service` | `user` | `system`)
- `actor_id` (string)
- `tenant_id` (string, nullable)
- `document_id` / `version_id` / `generation_request_id` (nullable)
- `request_id` (string)
- `metadata_json` (jsonb)
- `created_at_utc`

## Masking Rules for Input Payload
- Store full payload only in ephemeral execution memory.
- Persist only masked payload snapshot:
  - fields matching `*name*`, `*phone*`, `*email*`, `*inn*`, `*passport*`, `*account*` are masked by policy.
- Preserve `payload_hash_sha256` for dedupe and forensic correlation.

## Aggregation Model

### Near-real-time API aggregations
- Per document:
  - total calls,
  - success/failure counts,
  - p50/p95/p99 latency,
  - async queue wait metrics.
- Per client:
  - call volume,
  - error rates,
  - top error classes.

### Time windows
- Rolling 1h, 24h, 7d, 30d.
- Daily materialized summary for long-term dashboards.

## Indexing and Querying
- Partition high-volume tables by day or month (`generation_requests`, `audit_events`).
- Composite indexes:
  - (`document_id`, `created_at_utc`)
  - (`client_id`, `created_at_utc`)
  - (`status`, `created_at_utc`)
  - (`event_type`, `created_at_utc`)
- GIN index for selected JSONB fields (`metadata_json`, masked payload segments).

## Retention Policy
- `generation_requests`: 12 months (configurable).
- `generation_results`: business policy (e.g. 30-180 days).
- `audit_events`: minimum 12 months, recommended 24+ months for regulated profile.
- Summaries/materialized views: 24 months+.

## API Surface for Statistics
- `GET /documents/{documentId}/statistics`
- `GET /documents/{documentId}/events`
- `GET /clients/{clientId}/statistics` (admin scope)

## SLO and Alerting Signals
- Generation success rate < target threshold.
- P95 latency breach by profile.
- Queue lag and consumer idle issues.
- Validation failure spikes per template version.
- Security event anomaly (denied/rejected surge).

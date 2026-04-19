# E2E Test Cases Catalog (Industrial DOCX Service v1)

## Format
Each case is described as:
- **ID**
- **Preconditions**
- **Request**
- **Expected response**
- **Expected audit events**

## A. Auth and Access Control

### TC-AUTH-001: Valid service token can call sync generation
- ID: `TC-AUTH-001`
- Preconditions:
  - Existing published document version.
  - Client token with `docx.generate` scope.
- Request:
  - `POST /api/v1/generations/sync` with valid payload.
- Expected response:
  - `200` with DOCX binary or allowed result mode.
- Expected audit events:
  - `generation.requested`
  - `generation.started`
  - `generation.completed`

### TC-AUTH-002: Missing token is rejected
- ID: `TC-AUTH-002`
- Preconditions:
  - Endpoint publicly reachable.
- Request:
  - `POST /api/v1/generations/sync` without `Authorization`.
- Expected response:
  - `401` with standard error envelope.
- Expected audit events:
  - `auth.failed`

### TC-AUTH-003: Insufficient scope denied
- ID: `TC-AUTH-003`
- Preconditions:
  - Token without `docx.generate`.
- Request:
  - `POST /api/v1/generations/async`.
- Expected response:
  - `403`.
- Expected audit events:
  - `authz.denied`

## B. Template Lifecycle

### TC-TPL-001: Create document and draft version
- ID: `TC-TPL-001`
- Preconditions:
  - Authenticated analyst role.
- Request:
  - `POST /api/v1/documents` then `POST /api/v1/documents/{id}/versions`.
- Expected response:
  - `201` for both calls, version state `draft`.
- Expected audit events:
  - `document.created`
  - `version.created`

### TC-TPL-002: Publish version and immutability check
- ID: `TC-TPL-002`
- Preconditions:
  - Draft version exists.
  - Publisher role.
- Request:
  - `POST /api/v1/documents/{id}/versions/{versionId}/publish`
  - Then update immutable fields on same published version.
- Expected response:
  - Publish `200`, immutable update `409` or `422`.
- Expected audit events:
  - `version.published`
  - failed governance event for immutable update attempt.

## C. Tags and Conditional Rendering

### TC-COND-001: Conditional block true branch visible
- ID: `TC-COND-001`
- Preconditions:
  - Template with one conditional block (`if field_1 == "yes"`).
  - Published version.
- Request:
  - `POST /api/v1/generations/sync` with `field_1 = "yes"`.
- Expected response:
  - `200`, resulting document includes expected fragment.
- Expected audit events:
  - generation lifecycle success events.

### TC-COND-002: Conditional block false branch removed
- ID: `TC-COND-002`
- Preconditions:
  - Same template as above.
- Request:
  - `POST /api/v1/generations/sync` with `field_1 = "no"`.
- Expected response:
  - `200`, resulting document excludes conditional fragment.
- Expected audit events:
  - generation lifecycle success events.

### TC-COND-003: Large multi-page conditional fragment
- ID: `TC-COND-003`
- Preconditions:
  - 100+ page template with large conditional section.
  - Published version.
- Request:
  - `POST /api/v1/generations/async`.
- Expected response:
  - `202` accepted, eventual `succeeded` result.
- Expected audit events:
  - `generation.requested`
  - `generation.queued`
  - `generation.started`
  - `generation.completed`

## D. Signature Facsimile

### TC-SIGN-001: Upload valid signature asset
- ID: `TC-SIGN-001`
- Preconditions:
  - Draft version exists.
- Request:
  - `POST /api/v1/documents/{id}/versions/{versionId}/signature-assets` with PNG file.
- Expected response:
  - `201` with `signatureAssetId`.
- Expected audit events:
  - signature asset create event.

### TC-SIGN-002: Signature slot placement and generation
- ID: `TC-SIGN-002`
- Preconditions:
  - Signature asset and slot configured.
  - Published version.
- Request:
  - `POST /api/v1/generations/sync`.
- Expected response:
  - `200`, output DOCX contains signature in expected location.
- Expected audit events:
  - generation lifecycle success events.

### TC-SIGN-003: Invalid signature asset rejected
- ID: `TC-SIGN-003`
- Preconditions:
  - Attempt upload unsupported mime/oversized file.
- Request:
  - Upload to signature asset endpoint.
- Expected response:
  - `415` or `413`.
- Expected audit events:
  - `upload.rejected`.

## E. Sync and Async Generation

### TC-GEN-001: Sync generation with idempotency
- ID: `TC-GEN-001`
- Preconditions:
  - Published version exists.
- Request:
  - Two identical `POST /api/v1/generations/sync` calls with same `Idempotency-Key`.
- Expected response:
  - Same logical result reference; no duplicate processing side effects.
- Expected audit events:
  - first full lifecycle events,
  - second request marked as idempotent replay.

### TC-GEN-002: Async generation lifecycle
- ID: `TC-GEN-002`
- Preconditions:
  - Published version exists.
- Request:
  - `POST /api/v1/generations/async`, poll `GET /api/v1/generations/{jobId}`, then fetch result.
- Expected response:
  - `202` -> `running/succeeded` -> result available.
- Expected audit events:
  - queued/started/completed sequence in order.

### TC-GEN-003: Async callback signature validation
- ID: `TC-GEN-003`
- Preconditions:
  - Callback URL and secret configured.
- Request:
  - Async generation with callback.
- Expected response:
  - Service sends signed callback with verifiable signature headers.
- Expected audit events:
  - callback delivery success/failure event.

## F. Error and Retry Behavior

### TC-ERR-001: Payload schema mismatch
- ID: `TC-ERR-001`
- Preconditions:
  - Version schema requires field type constraints.
- Request:
  - Generation request with invalid payload type.
- Expected response:
  - `422` with validation error detail.
- Expected audit events:
  - `payload.validation_failed`.

### TC-ERR-002: Worker transient failure with retry
- ID: `TC-ERR-002`
- Preconditions:
  - Inject temporary storage/network fault in worker.
- Request:
  - Async generation.
- Expected response:
  - Automatic retry and eventual success or DLQ after retry budget.
- Expected audit events:
  - `generation.failed` (attempt level)
  - retry events
  - final success or terminal failure event.

### TC-ERR-003: Result not ready conflict
- ID: `TC-ERR-003`
- Preconditions:
  - Async job still queued/running.
- Request:
  - `GET /api/v1/generations/{jobId}/result`.
- Expected response:
  - `409` with status hint.
- Expected audit events:
  - optional access event, no completion event.

## G. Audit and Statistics Validation

### TC-STAT-001: Document statistics counters update
- ID: `TC-STAT-001`
- Preconditions:
  - Run at least 5 generation requests with mixed outcomes.
- Request:
  - `GET /api/v1/documents/{documentId}/statistics`.
- Expected response:
  - Totals and status counts match performed calls.
- Expected audit events:
  - read-statistics access event.

### TC-STAT-002: Caller attribution accuracy
- ID: `TC-STAT-002`
- Preconditions:
  - Requests from two different clients.
- Request:
  - Read statistics and top callers view.
- Expected response:
  - Caller counts correspond to source client IDs.
- Expected audit events:
  - read-statistics access event.

## H. Performance Smoke and Resilience

### TC-PERF-001: Sync latency smoke
- ID: `TC-PERF-001`
- Preconditions:
  - Warm cache, standard profile documents.
- Request:
  - 200 sync requests over controlled interval.
- Expected response:
  - P95 under agreed threshold (<1s target profile).
- Expected audit events:
  - normal generation lifecycle.

### TC-PERF-002: Async queue resilience under burst
- ID: `TC-PERF-002`
- Preconditions:
  - Burst profile load applied.
- Request:
  - High-rate async submissions.
- Expected response:
  - No data loss, bounded queue lag, acceptable completion ratio.
- Expected audit events:
  - queued/started/completed with no missing terminal events.

### TC-PERF-003: Worker restart recovery
- ID: `TC-PERF-003`
- Preconditions:
  - Jobs queued/running.
- Request:
  - Restart one worker instance during load.
- Expected response:
  - In-flight tasks retried/recovered without corruption.
- Expected audit events:
  - worker lifecycle incident event
  - request-level final states preserved.

### TC-DR-001: Backup and restore smoke
- ID: `TC-DR-001`
- Preconditions:
  - Generation store contains recent requests/events.
  - Access to backup target location.
- Request:
  - Run `scripts/backup_generation_store.sh`.
  - Run `scripts/dr_restore_smoke.sh` against produced bundle.
- Expected response:
  - Backup bundle created with checksum file.
  - Restore smoke validates required tables and readable records.
- Expected audit events:
  - Optional operational event for backup/restore workflow.

# Threat Model: DOCX Service v1

## Scope and Assets
- API surface (`/api/v1/*`) for template generation and operational reads.
- Template metadata and versions.
- Generation payload snapshots and resulting DOCX artifacts.
- Audit/statistics records and operational logs.
- Service credentials and bearer tokens.

## Trust Boundaries
- External callers -> API gateway/backend.
- Backend -> generation store (sqlite/postgres) and artifact filesystem/object storage.
- Backend -> webhook consumers (async callback channel).
- CI/CD -> runtime deployment target.

## Main Entry Points
- Generation endpoints: `/api/v1/generations/sync`, `/api/v1/generations/async`.
- Result/status/statistics/audit reads.
- Template management endpoints used by analysts/publishers.
- File upload endpoints for DOCX/signature assets.

## Threat Scenarios and Controls

### 1) Unauthorized access / token misuse
- Threat:
  - Missing/forged token calls.
  - Replay of leaked credentials.
- Controls:
  - Mandatory bearer auth for `/api/v1/*`.
  - Per-client rate limiting and request correlation (`X-Request-Id`).
  - Security audit events for auth failures and denied access.

### 2) Injection via payload/template data
- Threat:
  - Malformed payloads to trigger unexpected parser behavior.
  - Oversized/nested JSON payload abuse.
- Controls:
  - JSON Schema validation for version payloads.
  - Request size limits and strict error envelope.
  - Dependency audit gates in CI.

### 3) Malicious file handling (DOCX/OOXML)
- Threat:
  - Malformed OOXML structure or oversized compressed content.
  - Payloads intended to degrade parser performance.
- Controls:
  - Controlled parsing/render path in backend.
  - Async mode for heavy profiles and operational fallback.
  - DAST smoke in CI to detect obvious HTTP-layer misconfigurations.

### 4) Data leakage in logs/statistics/audit
- Threat:
  - Sensitive input reflected in logs or responses.
  - Over-broad audit/statistics access.
- Controls:
  - Structured logs with correlation-first fields.
  - Document-scoped statistics and audit APIs behind auth.
  - Operational policy to mask sensitive payload fields in analytics pipeline.

### 5) Availability degradation (DoS / queue pressure)
- Threat:
  - Burst traffic saturating sync path.
  - Async queue backlog and stuck jobs.
- Controls:
  - Sync/async split, idempotency support, queue depth metrics.
  - SLO smoke and canary scripts.
  - DR backup/restore smoke for recovery readiness.

## Residual Risks and Follow-Ups
- Static bearer token auth is acceptable for MVP-hardening but should be replaced with OAuth2 client credentials and scope validation.
- Add upload-layer anti-zip-bomb limits for strict production profile.
- Add signed webhook callback verification and replay protection fields.
- Expand DAST from baseline to authenticated staged scan with scenario corpus.

## Approval Checklist
- Threats mapped to implemented controls.
- Residual risks accepted and tracked in roadmap.
- Security test pack and DAST smoke run attached to release evidence.

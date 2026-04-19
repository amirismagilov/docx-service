# Release Evidence Pack v1

## Purpose
This document defines the minimum evidence set required for production go-live approval.

## Required Inputs
- Release identifier (git commit SHA / tag).
- Deployment window and responsible owner.
- Links to CI/CD workflow runs for this release.
- Links to generated artifacts (reports, logs, dashboards snapshots).

## Evidence Checklist

### 1) Build and Quality Gates
- `CI` workflow: successful run for release commit.
- `Deploy` workflow: successful rollout for release commit.
- OpenAPI validation passed.
- Backend tests passed.
- Frontend build passed.

### 2) Performance and Stability
- `SLO Smoke` workflow report for release candidate.
- Key latency evidence:
  - sync profile p95 trend,
  - async queue depth behavior.
- Canary smoke result (`scripts/canary_smoke.sh`) recorded.

### 3) Security
- Dependency audits passed (Python + frontend).
- `DAST Smoke` workflow report attached (`zap-report.html` / `zap-report.json`).
- `Security Smoke` workflow passed (`401/413/429` protections).
- Threat model reference:
  - `docs/security/threat-model-v1.md`
- Security test pack reference:
  - `docs/security/security-test-pack-v1.md`

### 4) Recovery and DR
- `DR Smoke` workflow passed.
- Backup bundle artifact stored and checksum verification attached.
- Latest restore smoke output attached.

### 5) Observability and Operations
- `/metrics` endpoint check in environment.
- Dashboard validation evidence:
  - `docs/observability/grafana/docx-v1-overview.dashboard.json`
- Runbook confirmation:
  - `docs/ops/runbook-v1.md`
- Canary checklist confirmation:
  - `docs/ops/canary-rollout-checklist-v1.md`

## Release Sign-Off Template
```text
Release: <tag-or-sha>
Date: <UTC timestamp>
Owner: <name>

CI Run URL: <url>
Deploy Run URL: <url>
SLO Smoke Run URL: <url>
DAST Smoke Run URL: <url>
Security Smoke Run URL: <url>
DR Smoke Run URL: <url>

Canary result: PASS | FAIL
Rollback readiness confirmed: YES | NO

Open risks:
- <risk 1>
- <risk 2>

Approvals:
- Engineering: <name/date>
- Security: <name/date>
- Operations: <name/date>
```

## Storage and Retention
- Store evidence pack alongside release artifacts in immutable release storage.
- Keep at least one year of release evidence history.

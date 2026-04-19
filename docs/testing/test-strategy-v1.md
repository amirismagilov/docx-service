# Test Strategy for Industrial DOCX Service v1

## Test Principles
- Shift-left quality: test design starts with API and domain contracts.
- Deterministic outputs for render engine through golden fixtures.
- Risk-based prioritization: security and correctness first, then performance.
- CI quality gates block regressions before merge.

## Test Pyramid

### 1) Unit tests
Focus:
- Placeholder replacement logic.
- Conditional visibility evaluation.
- Anchor resolution.
- Signature placement calculations.
- Payload masking and validation helpers.

Coverage target:
- Critical render and validation modules >= 85% branch coverage.

## 2) Integration tests
Focus:
- API + PostgreSQL + object storage + queue in dockerized environment.
- Version publish flow and immutability guarantees.
- Async lifecycle transitions and DLQ behavior.
- Idempotency and retries.

Coverage target:
- All critical API endpoints and failure paths covered.

## 3) Contract tests
Focus:
- OpenAPI schema conformance.
- Backward compatibility for API consumers.
- Error response envelope consistency (`code`, `message`, `requestId`).

Approach:
- Generate client stubs from `docs/api/openapi-v1.yaml`.
- Verify request/response examples against running service.

## 4) End-to-end tests
Focus:
- Full business flow from template setup to generated document retrieval.
- Sync and async generation with real DOCX fixtures.
- Statistics and audit event visibility.
- Role-based access restrictions.

Execution:
- Dedicated staging environment and seeded fixtures.
- Stable smoke subset on each merge, full suite nightly.

## 5) Performance and load tests
Tooling:
- k6 as baseline load runner.

Scenarios:
- Steady load: 2000 docs/day equivalent traffic.
- Burst load: 10x minute-level spike.
- Large-doc async queue stress.

Gates:
- Sync profile P95 < 1s.
- Async queue wait within agreed SLO.
- Error rate below threshold.

## 6) Security tests
Types:
- SAST, dependency scanning, secret scanning (CI mandatory).
- DAST against staging.
- Malicious corpus tests:
  - injection payloads,
  - malformed docx/xml,
  - zip bombs,
  - oversized assets.
- AuthN/AuthZ abuse tests:
  - invalid scopes,
  - replay attempts,
  - idempotency abuse.

## Environment Matrix
- `local`: fast unit/integration subset.
- `ci`: deterministic integration + contract + smoke e2e.
- `staging`: full e2e + load + DAST.
- `preprod`: release-candidate soak tests.

## CI Pipeline Quality Gates
1. Lint + static checks.
2. Unit tests.
3. Integration tests.
4. Contract tests.
5. Security scans.
6. Smoke e2e.

Release gates:
- Full e2e and load test pass in staging.
- No critical/high unresolved vulnerabilities.

## Test Data Strategy
- Synthetic fixtures for generic runs.
- Masked production-like fixtures for performance realism.
- Golden output corpus:
  - small/medium/large templates,
  - dense conditional blocks,
  - split-run placeholder edge cases,
  - facsimile insertion edge cases.

## Defect Management
- Severity classes:
  - `S1` data corruption/security bypass,
  - `S2` generation failure in supported profile,
  - `S3` non-critical UX/API issue.
- Mandatory RCA for recurring S1/S2 defects.

## Exit Criteria for v1
- 100% pass for required CI gates.
- Performance and security gates met in staging.
- Golden corpus shows no semantic output drift.
- All critical e2e scenarios documented and automated.

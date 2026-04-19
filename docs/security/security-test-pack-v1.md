# Security Test Pack v1

## Objective
Provide a repeatable minimum security validation set for each release candidate.

## Mandatory Gates
- Dependency scan:
  - Python: `pip-audit -r backend/requirements.txt`
  - Frontend: `npm audit --audit-level=high`
- DAST smoke workflow:
  - `.github/workflows/dast-smoke.yml`
- Security abuse smoke workflow:
  - `.github/workflows/security-smoke.yml`
- Auth and abuse regression:
  - Unauthorized access returns `401`.
  - Request size guard returns `413`.
  - Rate limit returns `429`.

## DAST Smoke Scope
- Target:
  - Running staging-like instance started in workflow.
- Paths:
  - `/health`
  - `/docs`
  - representative `/api/v1/*` paths (unauthenticated and authenticated probes where applicable).
- Tooling:
  - OWASP ZAP baseline scan in CI.

## Attack Corpus (to be expanded)
- Payload schema mismatch and nested payload stress.
- Header abuse (`X-Request-Id`, idempotency replay patterns).
- Malformed docx upload fixtures.
- Oversized request body checks.

## Evidence Artifacts
- ZAP baseline report (`html` + `json`) attached in workflow artifacts.
- CI security logs for dependency scans.
- Linked run IDs in release checklist.

## Exit Criteria
- No unresolved critical/high findings.
- No auth bypass regressions.
- DAST smoke status is green.
- Security checklist acknowledged by release owner.

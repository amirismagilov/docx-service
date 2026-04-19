# Security Contours for Industrial DOCX Service v1

## Purpose
Define two production-ready security contours and set the mandatory go-live baseline.

## Threat Model Scope
- API abuse (credential misuse, brute force, replay).
- Injection vectors (payload/template/docx/xml/parser level).
- Malicious files (zip bomb, oversized assets, malformed OOXML).
- Unauthorized access to templates/results/signatures.
- Data leakage in logs/statistics/audit exports.
- Async callback spoofing and tampering.

## Contour A: Baseline Enterprise (mandatory for v1)

### Identity and access
- OAuth2 client credentials for service-to-service API access.
- RBAC roles:
  - `analyst`: manage draft template entities.
  - `publisher`: publish immutable versions.
  - `integrator`: call generation APIs.
  - `auditor`: read statistics/audit endpoints.
  - `admin`: policy and tenant-level management.
- Least-privilege scopes per token (`docx.read`, `docx.write`, `docx.generate`).

### Data security
- TLS 1.2+ for all traffic.
- Encryption at rest:
  - PostgreSQL disk-level encryption.
  - Object storage bucket encryption.
- Sensitive payload fields masked in logs/audit snapshots.
- Configurable retention:
  - request snapshots (e.g. 90 days),
  - generated artifacts (policy-based),
  - audit events (minimum 1 year).

### Application security
- Strict input validation:
  - JSON schema validation for payload by template version.
  - hard limits for payload size, nesting, string lengths.
- File upload constraints:
  - MIME allow-list (`docx`, `png`, `jpeg`),
  - max size limits,
  - anti-zip-bomb checks (zip entry count, compression ratio, uncompressed size cap).
- Parser hardening:
  - disable unsafe XML features (XXE-safe parsing),
  - recursion/time/size limits in processing stages.
- No dynamic evaluation of user expressions in runtime process context.

### API and transport controls
- Rate limiting and burst control per client.
- Idempotency keys for generation endpoints.
- Mandatory request correlation ID.
- Signed callbacks for async webhooks (`X-Signature`, timestamp, nonce).

### SDLC security controls
- CI gates: SAST, dependency scan, secret scan.
- Mandatory code review with security checklist.
- DAST smoke against staging.
- Security regression tests for known attack corpus.

### Monitoring and incident response
- Security audit events:
  - auth failures,
  - role-denied operations,
  - publish actions,
  - generation failures with classification,
  - key/credential lifecycle changes.
- Alerting:
  - auth failure spikes,
  - unusual generation patterns,
  - parser rejection spikes.
- Incident runbook with RTO/RPO ownership.

## Contour B: Enhanced Regulated (for strict banking profile)

### Additional controls over baseline
- mTLS between all internal services.
- KMS/HSM-backed key management and key rotation evidence.
- Network segmentation with private-only service exposure.
- Immutable append-only audit stream to SIEM/WORM storage.
- Dual-control workflow for sensitive operations (publish, policy changes).
- Formal periodic pentest with remediation SLAs and evidence package.
- DR drills with signed reports and compliance artifacts.

## Recommended v1 Go-Live Choice
Use **Contour A (Baseline Enterprise)** as mandatory production gate.
Enable selected Contour B controls by risk profile:
- mTLS for critical integration zones.
- SIEM shipping for audit events.
- KMS-managed secrets for high-sensitivity tenants.

## Control Matrix
| Area | Baseline v1 | Enhanced |
|---|---|---|
| AuthN/AuthZ | OAuth2 + RBAC | OAuth2 + RBAC + mTLS |
| Encryption | TLS + at-rest | TLS + at-rest + KMS/HSM envelope |
| Audit | Structured DB audit | Immutable SIEM/WORM audit |
| Network | Standard private ingress | Segmented private mesh |
| Assurance | CI security gates + DAST | + formal pentest + DR evidence |

## Go-Live Security Exit Criteria
- No unresolved critical/high vulnerabilities.
- Threat model approved and mapped to controls.
- All mandatory controls from Contour A verified in staging.
- Security test pack (injection, parser abuse, authz bypass, replay) passes.
- Runbooks and on-call response validated in tabletop exercise.

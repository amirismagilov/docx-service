# Industrial DOCX Service v1 Delivery Roadmap

## Planning Assumptions
- Team: 4-6 engineers (backend/platform/qa), 1 product analyst, shared DevOps/SecOps.
- Sprint length: 2 weeks.
- Existing MVP remains functional during migration.

## Phase 0: Foundation (Weeks 1-2)
Scope:
- Confirm ADRs and target topology.
- Create repository interfaces and migration strategy.
- Define API v1 boundaries and compatibility policy.

Deliverables:
- Approved architecture ADR.
- OpenAPI v1 draft.
- Initial PostgreSQL schema draft.

Risks:
- Scope drift between MVP support and new architecture.
- Missing alignment on auth model.

Exit criteria:
- Architecture and API decisions approved.
- Backlog split into implementation epics with owners.

## Phase 1: Production Backend Skeleton (Weeks 3-6)
Scope:
- Replace in-memory state with PostgreSQL + object storage adapters.
- Introduce durable queue and worker service.
- Add idempotency and request correlation.

Deliverables:
- Running service with persistent metadata and binaries.
- Async generation path with status polling.
- Basic operational dashboards (health, queue depth, errors).

Risks:
- Data migration mismatches from MVP structures.
- Queue semantics edge cases.

Exit criteria:
- Core CRUD and async flow pass integration tests.
- Restart/recovery scenario validated.

## Phase 2: Rendering Hardening and Performance (Weeks 7-10)
Scope:
- Refactor render pipeline into modular services.
- Add compiled template indexing and caching.
- Add facsimile signature insertion.
- Optimize large template handling.

Deliverables:
- Deterministic rendering service with stage metrics.
- Benchmark report for S/M/L corpus.
- Sync/async routing policy by complexity.

Risks:
- OOXML edge-case regressions.
- Unstable performance under large conditional workloads.

Exit criteria:
- Sync target profile P95 < 1s in staging.
- Large docs stable via async path.

## Phase 3: Security and Compliance Hardening (Weeks 11-13)
Scope:
- Implement baseline security contour controls.
- Threat model completion and control mapping.
- Security automation in CI/CD.

Deliverables:
- RBAC, OAuth2 scopes, policy enforcement.
- Security test pack and DAST reports.
- Audit event completeness and retention config.

Risks:
- Late discovery of parser-level vulnerabilities.
- External auth integration delays.

Exit criteria:
- No open critical/high vulnerabilities.
- Security sign-off for production rollout.

## Phase 4: Stabilization and Rollout (Weeks 14-15)
Scope:
- Canary rollout with progressive traffic.
- Runbook validation and on-call readiness.
- Documentation handover for integrators.

Deliverables:
- Go-live checklist completed.
- API integration guide and examples.
- E2E catalog and release evidence pack.

Risks:
- Unexpected tenant-specific template complexity.
- Operational gaps during canary.

Exit criteria:
- Canary SLO compliance.
- Production go-live approval.

## Cross-Phase Streams
- Documentation maintenance: API docs, architecture docs, playbooks.
- Test automation expansion with each phase.
- Weekly risk review and mitigation updates.

## Milestone Map
- `M0`: Architecture approved.
- `M1`: Persistent backend and async queue online.
- `M2`: Render engine hardened and benchmarked.
- `M3`: Security baseline passed.
- `M4`: Production rollout complete.

## Go/No-Go Checklist
- Throughput and latency targets validated.
- Security baseline controls operational.
- Audit/statistics endpoints accurate.
- Backup/restore and DR smoke passed.
- Integrator onboarding docs accepted.

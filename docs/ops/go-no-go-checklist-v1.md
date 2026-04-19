# Go/No-Go Checklist v1

## Goal
Provide a quick deterministic readiness check before production go-live decision.

## Required Checks
- CI for release commit is green.
- Deploy for release commit is green.
- Latest smoke workflows are successful:
  - `SLO Smoke`
  - `DAST Smoke`
  - `Security Smoke`
  - `DR Smoke`
- Release evidence pack draft is generated and attached.

## Automated Command
Use commit-scoped check:
```bash
python scripts/go_no_go_check.py --commit <sha>
```

For pre-release dry run where smoke runs may be missing for the same commit:
```bash
python scripts/go_no_go_check.py --commit <sha> --allow-missing-smokes
```

GitHub Actions option:
- Run `Go No-Go Check` workflow (`.github/workflows/go-no-go.yml`).
- Download artifact `go-no-go-report` and attach to release evidence.

## Manual Confirmation
- Canary rollout checklist completed:
  - `docs/ops/canary-rollout-checklist-v1.md`
- Runbook review completed:
  - `docs/ops/runbook-v1.md`
- Release evidence compiled:
  - `docs/ops/release-evidence-pack-v1.md`

## Decision Record Template
```text
Release: <sha/tag>
Decision: GO | NO-GO
Time (UTC): <timestamp>
Approvers:
- Engineering: <name>
- Security: <name>
- Operations: <name>
Notes:
- <note>
```

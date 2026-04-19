#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass


@dataclass
class WorkflowStatus:
    name: str
    status: str
    conclusion: str
    url: str

    @property
    def is_success(self) -> bool:
        return self.status == "completed" and self.conclusion == "success"


REQUIRED_WORKFLOWS = [
    "CI",
    "Deploy",
    "SLO Smoke",
    "DAST Smoke",
    "Security Smoke",
    "DR Smoke",
]


def _run(cmd: list[str]) -> str:
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return result.stdout


def _resolve_commit_sha(commit_ref: str) -> str:
    return _run(["git", "rev-parse", commit_ref]).strip()


def _latest_workflow_run(name: str, commit_sha: str | None) -> WorkflowStatus | None:
    cmd = [
        "gh",
        "run",
        "list",
        "--workflow",
        name,
        "--limit",
        "1",
        "--json",
        "status,conclusion,url,headSha",
    ]
    if commit_sha:
        cmd.extend(["--commit", commit_sha])
    rows = json.loads(_run(cmd))
    if not rows:
        return None
    row = rows[0]
    return WorkflowStatus(
        name=name,
        status=row.get("status", "unknown"),
        conclusion=row.get("conclusion", ""),
        url=row.get("url", ""),
    )


def _format_line(item: WorkflowStatus | None, workflow_name: str) -> str:
    if item is None:
        return f"- [ ] `{workflow_name}` `missing`"
    mark = "x" if item.is_success else " "
    status = f"{item.status}/{item.conclusion or 'n/a'}"
    return f"- [{mark}] `{item.name}` `{status}` {item.url}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate go/no-go workflow readiness.")
    parser.add_argument(
        "--commit",
        default=None,
        help="Commit ref (default: HEAD). Uses commit-scoped checks for CI/Deploy and smoke workflows.",
    )
    parser.add_argument(
        "--allow-missing-smokes",
        action="store_true",
        help="Do not fail when smoke workflows are missing for the specified commit.",
    )
    args = parser.parse_args()

    commit_sha = _resolve_commit_sha(args.commit or "HEAD")
    statuses: list[WorkflowStatus | None] = []
    failures: list[str] = []

    for wf in REQUIRED_WORKFLOWS:
        status = _latest_workflow_run(wf, commit_sha=commit_sha)
        statuses.append(status)
        if status is None:
            if wf in {"SLO Smoke", "DAST Smoke", "Security Smoke", "DR Smoke"} and args.allow_missing_smokes:
                continue
            failures.append(f"{wf}: missing run")
            continue
        if not status.is_success:
            failures.append(f"{wf}: {status.status}/{status.conclusion or 'n/a'}")

    print("# Go/No-Go Check")
    print("")
    print(f"Release commit: `{commit_sha}`")
    print("")
    for workflow_name, item in zip(REQUIRED_WORKFLOWS, statuses):
        print(_format_line(item, workflow_name))

    if failures:
        print("")
        print("Result: FAIL")
        print("Details:")
        for f in failures:
            print(f"- {f}")
        return 1

    print("")
    print("Result: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())

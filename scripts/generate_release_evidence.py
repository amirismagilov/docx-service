#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class WorkflowRef:
    label: str
    workflow_name: str


WORKFLOWS: list[WorkflowRef] = [
    WorkflowRef(label="CI Run URL", workflow_name="CI"),
    WorkflowRef(label="Deploy Run URL", workflow_name="Deploy"),
    WorkflowRef(label="SLO Smoke Run URL", workflow_name="SLO Smoke"),
    WorkflowRef(label="DAST Smoke Run URL", workflow_name="DAST Smoke"),
    WorkflowRef(label="Security Smoke Run URL", workflow_name="Security Smoke"),
    WorkflowRef(label="DR Smoke Run URL", workflow_name="DR Smoke"),
]


def _run(command: list[str]) -> str:
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    return result.stdout


def _latest_run_url(workflow_name: str, commit_sha: str) -> str:
    stdout = _run(
        [
            "gh",
            "run",
            "list",
            "--workflow",
            workflow_name,
            "--commit",
            commit_sha,
            "--limit",
            "1",
            "--json",
            "url",
        ]
    )
    runs = json.loads(stdout)
    if not runs:
        return "<not-found>"
    return runs[0].get("url", "<not-found>")


def _build_content(commit_sha: str, owner: str) -> str:
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines: list[str] = []
    lines.append("# Release Evidence Record")
    lines.append("")
    lines.append(f"Release: `{commit_sha}`")
    lines.append(f"Date (UTC): `{now_utc}`")
    lines.append(f"Owner: `{owner}`")
    lines.append("")
    for wf in WORKFLOWS:
        lines.append(f"{wf.label}: {_latest_run_url(wf.workflow_name, commit_sha)}")
    lines.append("")
    lines.append("Canary result: PASS | FAIL")
    lines.append("Rollback readiness confirmed: YES | NO")
    lines.append("")
    lines.append("Open risks:")
    lines.append("- <risk 1>")
    lines.append("- <risk 2>")
    lines.append("")
    lines.append("Approvals:")
    lines.append("- Engineering: <name/date>")
    lines.append("- Security: <name/date>")
    lines.append("- Operations: <name/date>")
    lines.append("")
    lines.append("References:")
    lines.append("- docs/ops/release-evidence-pack-v1.md")
    lines.append("- docs/ops/runbook-v1.md")
    return "\n".join(lines) + "\n"


def _git_head_sha() -> str:
    return _run(["git", "rev-parse", "HEAD"]).strip()


def _resolve_commit_sha(commit_ref: str) -> str:
    return _run(["git", "rev-parse", commit_ref]).strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate release evidence markdown for a commit.")
    parser.add_argument("--commit", default=None, help="Commit SHA (default: HEAD).")
    parser.add_argument("--owner", default="release-owner", help="Evidence owner name.")
    parser.add_argument(
        "--output",
        default=None,
        help="Output markdown path (default: docs/ops/evidence/release-<sha>.md).",
    )
    args = parser.parse_args()

    commit_ref = args.commit or _git_head_sha()
    commit_sha = _resolve_commit_sha(commit_ref)
    output_path = Path(args.output or f"docs/ops/evidence/release-{commit_sha}.md")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(_build_content(commit_sha=commit_sha, owner=args.owner), encoding="utf-8")
    print(f"Release evidence generated: {output_path}")


if __name__ == "__main__":
    main()

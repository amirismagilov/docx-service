from __future__ import annotations

from pathlib import Path

import yaml
from openapi_spec_validator import validate_spec


def main() -> None:
    spec_path = Path("docs/api/openapi-v1.yaml")
    if not spec_path.is_file():
        raise SystemExit("OpenAPI spec not found: docs/api/openapi-v1.yaml")
    payload = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    validate_spec(payload)
    required_paths = {
        "/generations/sync",
        "/generations/async",
        "/generations/{jobId}",
        "/generations/{jobId}/result",
    }
    paths = set((payload.get("paths") or {}).keys())
    missing = sorted(required_paths - paths)
    if missing:
        raise SystemExit(f"OpenAPI required paths missing: {', '.join(missing)}")
    print("OpenAPI v1 spec validation passed.")


if __name__ == "__main__":
    main()

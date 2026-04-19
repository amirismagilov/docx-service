from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class GenerationRecord:
    id: uuid.UUID
    document_id: uuid.UUID
    version_id: uuid.UUID
    mode: str
    status: str
    request_id: str
    idempotency_key: str | None
    payload_json: str
    payload_masked_json: str
    payload_hash_sha256: str
    error_code: str | None
    error_message: str | None
    file_name: str | None
    mime_type: str | None
    storage_path: str | None
    size_bytes: int | None
    sha256: str | None
    created_at_utc: str
    started_at_utc: str | None
    finished_at_utc: str | None
    latency_ms: int | None


class GenerationStore(Protocol):
    def close(self) -> None: ...

    def create_generation(
        self,
        *,
        document_id: uuid.UUID,
        version_id: uuid.UUID,
        mode: str,
        request_id: str,
        idempotency_key: str | None,
        payload: dict[str, Any],
        status: str,
    ) -> GenerationRecord: ...

    def find_by_idempotency_key(
        self, *, document_id: uuid.UUID, version_id: uuid.UUID, idempotency_key: str
    ) -> GenerationRecord | None: ...

    def get_generation(self, generation_id: uuid.UUID) -> GenerationRecord: ...

    def mark_running(self, generation_id: uuid.UUID) -> None: ...

    def mark_succeeded(self, generation_id: uuid.UUID, file_name: str, content: bytes) -> None: ...

    def mark_failed(self, generation_id: uuid.UUID, error_code: str, error_message: str) -> None: ...

    def add_audit_event(
        self,
        *,
        generation_request_id: uuid.UUID,
        event_type: str,
        severity: str,
        actor_id: str,
        request_id: str,
        metadata: dict[str, Any],
    ) -> None: ...

    def list_queued_generation_ids(self) -> list[uuid.UUID]: ...

    def get_document_statistics(self, document_id: uuid.UUID) -> dict[str, Any]: ...


def percentile(values: list[int], p: int) -> int:
    if not values:
        return 0
    idx = max(0, min(len(values) - 1, round((p / 100) * (len(values) - 1))))
    return values[idx]

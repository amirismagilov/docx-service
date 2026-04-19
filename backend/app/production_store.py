from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.generation_store import GenerationRecord, percentile


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _dt_from_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    return datetime.fromisoformat(normalized)


def _mask_payload(data: dict[str, Any]) -> dict[str, Any]:
    sensitive_tokens = ("name", "phone", "email", "passport", "account", "inn")
    out: dict[str, Any] = {}
    for key, value in data.items():
        key_l = key.lower()
        if any(token in key_l for token in sensitive_tokens):
            out[key] = "***"
        else:
            out[key] = value
    return out


class ProductionStore:
    def __init__(self, db_path: Path, result_dir: Path) -> None:
        self._db_path = db_path
        self._result_dir = result_dir
        self._lock = threading.Lock()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        result_dir.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _init_schema(self) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                create table if not exists generation_requests (
                  id text primary key,
                  document_id text not null,
                  version_id text not null,
                  mode text not null,
                  status text not null,
                  request_id text not null,
                  idempotency_key text,
                  payload_json text not null,
                  payload_masked_json text not null,
                  payload_hash_sha256 text not null,
                  error_code text,
                  error_message text,
                  file_name text,
                  mime_type text,
                  storage_path text,
                  size_bytes integer,
                  sha256 text,
                  created_at_utc text not null,
                  started_at_utc text,
                  finished_at_utc text,
                  latency_ms integer
                )
                """
            )
            cur.execute(
                "create index if not exists ix_generation_requests_document_time on generation_requests(document_id, created_at_utc)"
            )
            cur.execute(
                "create index if not exists ix_generation_requests_status_time on generation_requests(status, created_at_utc)"
            )
            cur.execute(
                """
                create table if not exists audit_events (
                  id text primary key,
                  generation_request_id text,
                  event_type text not null,
                  severity text not null,
                  actor_id text not null,
                  request_id text not null,
                  metadata_json text not null,
                  created_at_utc text not null
                )
                """
            )
            self._conn.commit()

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
    ) -> GenerationRecord:
        payload_json = json.dumps(payload, ensure_ascii=False)
        payload_masked_json = json.dumps(_mask_payload(payload), ensure_ascii=False)
        payload_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        now = _utc_now_iso()
        gid = uuid.uuid4()
        with self._lock:
            self._conn.execute(
                """
                insert into generation_requests (
                  id, document_id, version_id, mode, status, request_id, idempotency_key,
                  payload_json, payload_masked_json, payload_hash_sha256, created_at_utc
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(gid),
                    str(document_id),
                    str(version_id),
                    mode,
                    status,
                    request_id,
                    idempotency_key,
                    payload_json,
                    payload_masked_json,
                    payload_hash,
                    now,
                ),
            )
            self._conn.commit()
        self.add_audit_event(
            generation_request_id=gid,
            event_type="generation.requested",
            severity="info",
            actor_id="system",
            request_id=request_id,
            metadata={"mode": mode, "documentId": str(document_id), "versionId": str(version_id)},
        )
        return self.get_generation(gid)

    def find_by_idempotency_key(
        self, *, document_id: uuid.UUID, version_id: uuid.UUID, idempotency_key: str
    ) -> GenerationRecord | None:
        with self._lock:
            row = self._conn.execute(
                """
                select * from generation_requests
                where document_id = ? and version_id = ? and idempotency_key = ?
                order by created_at_utc desc limit 1
                """,
                (str(document_id), str(version_id), idempotency_key),
            ).fetchone()
        return self._row_to_record(row) if row else None

    def get_generation(self, generation_id: uuid.UUID) -> GenerationRecord:
        with self._lock:
            row = self._conn.execute(
                "select * from generation_requests where id = ?",
                (str(generation_id),),
            ).fetchone()
        if row is None:
            raise KeyError("Generation not found")
        return self._row_to_record(row)

    def mark_running(self, generation_id: uuid.UUID) -> None:
        started = _utc_now_iso()
        with self._lock:
            self._conn.execute(
                "update generation_requests set status = 'running', started_at_utc = ? where id = ?",
                (started, str(generation_id)),
            )
            self._conn.commit()
        rec = self.get_generation(generation_id)
        self.add_audit_event(
            generation_request_id=generation_id,
            event_type="generation.started",
            severity="info",
            actor_id="worker",
            request_id=rec.request_id,
            metadata={},
        )

    def mark_succeeded(self, generation_id: uuid.UUID, file_name: str, content: bytes) -> None:
        finished = _utc_now_iso()
        checksum = hashlib.sha256(content).hexdigest()
        out_path = self._result_dir / f"{generation_id}.docx"
        out_path.write_bytes(content)
        rec = self.get_generation(generation_id)
        latency_ms = None
        created = _dt_from_iso(rec.created_at_utc)
        finished_dt = _dt_from_iso(finished)
        if created and finished_dt:
            latency_ms = int((finished_dt - created).total_seconds() * 1000)
        with self._lock:
            self._conn.execute(
                """
                update generation_requests
                set status = 'succeeded',
                    file_name = ?,
                    mime_type = ?,
                    storage_path = ?,
                    size_bytes = ?,
                    sha256 = ?,
                    finished_at_utc = ?,
                    latency_ms = ?
                where id = ?
                """,
                (
                    file_name,
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    str(out_path),
                    len(content),
                    checksum,
                    finished,
                    latency_ms,
                    str(generation_id),
                ),
            )
            self._conn.commit()
        self.add_audit_event(
            generation_request_id=generation_id,
            event_type="generation.completed",
            severity="info",
            actor_id="worker",
            request_id=rec.request_id,
            metadata={"sizeBytes": len(content)},
        )

    def mark_failed(self, generation_id: uuid.UUID, error_code: str, error_message: str) -> None:
        finished = _utc_now_iso()
        with self._lock:
            self._conn.execute(
                """
                update generation_requests
                set status = 'failed',
                    error_code = ?,
                    error_message = ?,
                    finished_at_utc = ?
                where id = ?
                """,
                (error_code, error_message, finished, str(generation_id)),
            )
            self._conn.commit()
        rec = self.get_generation(generation_id)
        self.add_audit_event(
            generation_request_id=generation_id,
            event_type="generation.failed",
            severity="error",
            actor_id="worker",
            request_id=rec.request_id,
            metadata={"errorCode": error_code},
        )

    def add_audit_event(
        self,
        *,
        generation_request_id: uuid.UUID,
        event_type: str,
        severity: str,
        actor_id: str,
        request_id: str,
        metadata: dict[str, Any],
    ) -> None:
        with self._lock:
            self._conn.execute(
                """
                insert into audit_events (
                  id, generation_request_id, event_type, severity, actor_id, request_id, metadata_json, created_at_utc
                ) values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    str(generation_request_id),
                    event_type,
                    severity,
                    actor_id,
                    request_id,
                    json.dumps(metadata, ensure_ascii=False),
                    _utc_now_iso(),
                ),
            )
            self._conn.commit()

    def list_queued_generation_ids(self) -> list[uuid.UUID]:
        with self._lock:
            rows = self._conn.execute(
                "select id from generation_requests where status = 'queued' order by created_at_utc asc"
            ).fetchall()
        return [uuid.UUID(row["id"]) for row in rows]

    def get_document_statistics(
        self,
        document_id: uuid.UUID,
        *,
        from_utc: datetime | None = None,
        to_utc: datetime | None = None,
    ) -> dict[str, Any]:
        where = ["document_id = ?"]
        params: list[Any] = [str(document_id)]
        if from_utc is not None:
            where.append("created_at_utc >= ?")
            params.append(from_utc.isoformat().replace("+00:00", "Z"))
        if to_utc is not None:
            where.append("created_at_utc <= ?")
            params.append(to_utc.isoformat().replace("+00:00", "Z"))
        where_sql = " and ".join(where)
        with self._lock:
            rows = self._conn.execute(
                f"select status, count(*) as cnt from generation_requests where {where_sql} group by status",
                tuple(params),
            ).fetchall()
            latency_rows = self._conn.execute(
                f"select latency_ms from generation_requests where {where_sql} and latency_ms is not null order by latency_ms",
                tuple(params),
            ).fetchall()
            top_callers_rows = self._conn.execute(
                """
                select actor_id, count(*) as calls
                from audit_events
                where event_type = 'generation.requested'
                  and generation_request_id in (select id from generation_requests where """
                + where_sql
                + """)
                group by actor_id
                order by calls desc
                limit 5
                """,
                tuple(params),
            ).fetchall()
            daily_rows = self._conn.execute(
                f"""
                select substr(created_at_utc, 1, 10) as day, count(*) as calls
                from generation_requests
                where {where_sql}
                group by substr(created_at_utc, 1, 10)
                order by day asc
                """,
                tuple(params),
            ).fetchall()
        by_status = {row["status"]: int(row["cnt"]) for row in rows}
        total_calls = sum(by_status.values())
        latencies = [int(row["latency_ms"]) for row in latency_rows]
        return {
            "documentId": str(document_id),
            "totals": {
                "calls": total_calls,
                "success": by_status.get("succeeded", 0),
                "failed": by_status.get("failed", 0),
            },
            "byStatus": by_status,
            "latency": {
                "p50Ms": percentile(latencies, 50),
                "p95Ms": percentile(latencies, 95),
                "p99Ms": percentile(latencies, 99),
            },
            "topCallers": [{"clientId": row["actor_id"], "calls": int(row["calls"])} for row in top_callers_rows],
            "dailyBuckets": [{"day": row["day"], "calls": int(row["calls"])} for row in daily_rows],
        }

    def get_document_events(
        self,
        document_id: uuid.UUID,
        *,
        from_utc: datetime | None = None,
        to_utc: datetime | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        where = ["generation_request_id in (select id from generation_requests where document_id = ?)"]
        params: list[Any] = [str(document_id)]
        if from_utc is not None:
            where.append("created_at_utc >= ?")
            params.append(from_utc.isoformat().replace("+00:00", "Z"))
        if to_utc is not None:
            where.append("created_at_utc <= ?")
            params.append(to_utc.isoformat().replace("+00:00", "Z"))
        where_sql = " and ".join(where)
        capped_limit = max(1, min(limit, 500))
        with self._lock:
            rows = self._conn.execute(
                f"""
                select event_type, severity, actor_id, request_id, metadata_json, created_at_utc
                from audit_events
                where {where_sql}
                order by created_at_utc desc
                limit ?
                """,
                tuple(params) + (capped_limit,),
            ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            metadata_raw = row["metadata_json"] or "{}"
            try:
                metadata = json.loads(metadata_raw)
            except json.JSONDecodeError:
                metadata = {"raw": metadata_raw}
            out.append(
                {
                    "eventType": row["event_type"],
                    "severity": row["severity"],
                    "actorId": row["actor_id"],
                    "requestId": row["request_id"],
                    "metadata": metadata,
                    "createdAtUtc": row["created_at_utc"],
                }
            )
        return out

    def _row_to_record(self, row: sqlite3.Row) -> GenerationRecord:
        return GenerationRecord(
            id=uuid.UUID(row["id"]),
            document_id=uuid.UUID(row["document_id"]),
            version_id=uuid.UUID(row["version_id"]),
            mode=row["mode"],
            status=row["status"],
            request_id=row["request_id"],
            idempotency_key=row["idempotency_key"],
            payload_json=row["payload_json"],
            payload_masked_json=row["payload_masked_json"],
            payload_hash_sha256=row["payload_hash_sha256"],
            error_code=row["error_code"],
            error_message=row["error_message"],
            file_name=row["file_name"],
            mime_type=row["mime_type"],
            storage_path=row["storage_path"],
            size_bytes=row["size_bytes"],
            sha256=row["sha256"],
            created_at_utc=row["created_at_utc"],
            started_at_utc=row["started_at_utc"],
            finished_at_utc=row["finished_at_utc"],
            latency_ms=row["latency_ms"],
        )

from __future__ import annotations

from pathlib import Path

from app.generation_store import GenerationStore
from app.postgres_store import PostgresStore
from app.production_store import ProductionStore


def create_generation_store(
    *,
    backend: str,
    sqlite_db_path: Path,
    result_dir: Path,
    pg_dsn: str | None,
) -> GenerationStore:
    normalized = (backend or "sqlite").strip().lower()
    if normalized == "postgres":
        if not pg_dsn:
            raise RuntimeError("DOCX_SERVICE_PG_DSN is required for postgres generation store backend.")
        return PostgresStore(pg_dsn, result_dir)
    if normalized != "sqlite":
        raise RuntimeError(f"Unsupported generation store backend: {backend}")
    return ProductionStore(sqlite_db_path, result_dir)

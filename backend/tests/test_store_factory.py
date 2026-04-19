from pathlib import Path

import pytest

from app.store_factory import create_generation_store


def test_create_generation_store_defaults_to_sqlite(tmp_path: Path) -> None:
    store = create_generation_store(
        backend="sqlite",
        sqlite_db_path=tmp_path / "prod.db",
        result_dir=tmp_path / "generated",
        pg_dsn=None,
    )
    try:
        assert (tmp_path / "prod.db").is_file()
    finally:
        store.close()


def test_create_generation_store_rejects_missing_postgres_dsn(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError):
        create_generation_store(
            backend="postgres",
            sqlite_db_path=tmp_path / "prod.db",
            result_dir=tmp_path / "generated",
            pg_dsn=None,
        )

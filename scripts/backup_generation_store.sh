#!/usr/bin/env bash
set -euo pipefail

STORE_BACKEND="${DOCX_SERVICE_GENERATION_STORE:-sqlite}"
SQLITE_DB_PATH="${DOCX_SERVICE_DB_PATH:-./backend/data/production.db}"
POSTGRES_DSN="${DOCX_SERVICE_PG_DSN:-}"
RESULTS_DIR="${DOCX_SERVICE_RESULTS_DIR:-./backend/data/results}"
BACKUP_ROOT="${BACKUP_ROOT:-/tmp/docx-service-backups}"
TIMESTAMP="${TIMESTAMP:-$(date -u +%Y%m%dT%H%M%SZ)}"
BACKUP_DIR="${BACKUP_ROOT}/${TIMESTAMP}"

mkdir -p "${BACKUP_DIR}"

echo "Creating backup bundle at ${BACKUP_DIR}"

if [[ "${STORE_BACKEND}" == "sqlite" ]]; then
  if [[ ! -f "${SQLITE_DB_PATH}" ]]; then
    echo "SQLite DB not found: ${SQLITE_DB_PATH}"
    exit 1
  fi
  cp "${SQLITE_DB_PATH}" "${BACKUP_DIR}/generation_store.sqlite"
  echo "SQLite snapshot saved"
elif [[ "${STORE_BACKEND}" == "postgres" ]]; then
  if [[ -z "${POSTGRES_DSN}" ]]; then
    echo "DOCX_SERVICE_PG_DSN is required for postgres backups"
    exit 1
  fi
  if ! command -v pg_dump >/dev/null 2>&1; then
    echo "pg_dump is required for postgres backups"
    exit 1
  fi
  pg_dump --no-owner --no-privileges --format=plain "${POSTGRES_DSN}" > "${BACKUP_DIR}/generation_store.sql"
  echo "Postgres dump saved"
else
  echo "Unsupported DOCX_SERVICE_GENERATION_STORE: ${STORE_BACKEND}"
  exit 1
fi

if [[ -d "${RESULTS_DIR}" ]]; then
  tar -czf "${BACKUP_DIR}/results.tar.gz" -C "${RESULTS_DIR}" .
  echo "Result artifacts archived"
else
  echo "WARN: results directory does not exist: ${RESULTS_DIR}"
fi

{
  echo "timestamp=${TIMESTAMP}"
  echo "store_backend=${STORE_BACKEND}"
  echo "sqlite_db_path=${SQLITE_DB_PATH}"
  echo "results_dir=${RESULTS_DIR}"
} > "${BACKUP_DIR}/metadata.txt"

(
  cd "${BACKUP_DIR}"
  shasum -a 256 ./* > checksums.sha256
)

echo "Backup completed: ${BACKUP_DIR}"
echo "Verify with: (cd ${BACKUP_DIR} && shasum -a 256 -c checksums.sha256)"

#!/usr/bin/env bash
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-}"
RESTORE_ROOT="${RESTORE_ROOT:-/tmp/docx-service-dr-restore}"
RESTORE_SQLITE_PATH="${RESTORE_SQLITE_PATH:-${RESTORE_ROOT}/generation_store.sqlite}"
RESTORE_PG_DSN="${RESTORE_PG_DSN:-}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if [[ -z "${BACKUP_DIR}" ]]; then
  echo "BACKUP_DIR is required"
  exit 1
fi
if [[ ! -d "${BACKUP_DIR}" ]]; then
  echo "Backup directory does not exist: ${BACKUP_DIR}"
  exit 1
fi
if [[ ! -f "${BACKUP_DIR}/checksums.sha256" ]]; then
  echo "checksums.sha256 is missing in ${BACKUP_DIR}"
  exit 1
fi

echo "1) Verifying backup checksums"
(cd "${BACKUP_DIR}" && shasum -a 256 -c checksums.sha256)

if [[ -f "${BACKUP_DIR}/generation_store.sqlite" ]]; then
  echo "2) Restoring SQLite snapshot"
  mkdir -p "$(dirname "${RESTORE_SQLITE_PATH}")"
  cp "${BACKUP_DIR}/generation_store.sqlite" "${RESTORE_SQLITE_PATH}"

  echo "3) Running SQLite DR smoke queries"
  "${PYTHON_BIN}" - <<'PY' "${RESTORE_SQLITE_PATH}"
import sqlite3
import sys

path = sys.argv[1]
conn = sqlite3.connect(path)
cur = conn.cursor()

required = ("generation_requests", "audit_events")
for table in required:
    row = cur.execute(
        "select name from sqlite_master where type='table' and name = ?",
        (table,),
    ).fetchone()
    if not row:
        raise SystemExit(f"Missing required table after restore: {table}")

requests_total = cur.execute("select count(1) from generation_requests").fetchone()[0]
events_total = cur.execute("select count(1) from audit_events").fetchone()[0]

print(f"generation_requests={requests_total}")
print(f"audit_events={events_total}")
print("SQLite restore smoke passed")
PY
elif [[ -f "${BACKUP_DIR}/generation_store.sql" ]]; then
  echo "2) Postgres dump detected"
  if [[ -z "${RESTORE_PG_DSN}" ]]; then
    echo "RESTORE_PG_DSN is required to test Postgres restore"
    exit 1
  fi
  if ! command -v psql >/dev/null 2>&1; then
    echo "psql is required for Postgres restore smoke"
    exit 1
  fi

  echo "3) Restoring dump into target Postgres DSN"
  psql "${RESTORE_PG_DSN}" -v ON_ERROR_STOP=1 -f "${BACKUP_DIR}/generation_store.sql" >/dev/null

  echo "4) Running Postgres DR smoke queries"
  psql "${RESTORE_PG_DSN}" -v ON_ERROR_STOP=1 -c "select count(1) as generation_requests from generation_requests;"
  psql "${RESTORE_PG_DSN}" -v ON_ERROR_STOP=1 -c "select count(1) as audit_events from audit_events;"
  echo "Postgres restore smoke passed"
else
  echo "No known backup payload found in ${BACKUP_DIR}"
  exit 1
fi

if [[ -f "${BACKUP_DIR}/results.tar.gz" ]]; then
  RESULTS_RESTORE_DIR="${RESTORE_ROOT}/results"
  echo "4) Restoring result artifacts into ${RESULTS_RESTORE_DIR}"
  mkdir -p "${RESULTS_RESTORE_DIR}"
  tar -xzf "${BACKUP_DIR}/results.tar.gz" -C "${RESULTS_RESTORE_DIR}"
fi

echo "DR restore smoke finished successfully"

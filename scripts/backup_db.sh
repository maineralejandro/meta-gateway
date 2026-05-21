#!/usr/bin/env bash
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-./backups}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/hermes_${TIMESTAMP}.sql.gz"

mkdir -p "${BACKUP_DIR}"

echo "Backing up Supabase DB to ${BACKUP_FILE}..."

docker exec supabase_db_app pg_dump \
  -U postgres \
  -d postgres \
  --no-owner \
  --no-privileges \
  --clean \
  --if-exists \
  | gzip > "${BACKUP_FILE}"

SIZE=$(du -h "${BACKUP_FILE}" | cut -f1)
echo "Backup complete: ${BACKUP_FILE} (${SIZE})"

COUNT=$(ls -1 "${BACKUP_DIR}"/hermes_*.sql.gz 2>/dev/null | wc -l)
MAX_BACKUPS="${MAX_BACKUPS:-10}"
if [ "${COUNT}" -gt "${MAX_BACKUPS}" ]; then
  echo "Rotating old backups (keeping ${MAX_BACKUPS})..."
  ls -1t "${BACKUP_DIR}"/hermes_*.sql.gz | tail -n +"$((MAX_BACKUPS + 1))" | xargs rm -f
fi

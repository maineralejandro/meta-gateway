#!/usr/bin/env bash
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "Usage: $0 <backup_file.sql.gz>"
  echo "Available backups:"
  ls -1t backups/hermes_*.sql.gz 2>/dev/null || echo "  (none found in ./backups/)"
  exit 1
fi

BACKUP_FILE="$1"

if [ ! -f "${BACKUP_FILE}" ]; then
  echo "Error: ${BACKUP_FILE} not found"
  exit 1
fi

echo "WARNING: This will DROP and recreate all tables in the Supabase DB."
read -r -p "Continue? [y/N] " confirm
if [ "${confirm}" != "y" ] && [ "${confirm}" != "Y" ]; then
  echo "Aborted."
  exit 0
fi

echo "Restoring from ${BACKUP_FILE}..."

gunzip -c "${BACKUP_FILE}" | docker exec -i supabase_db_app psql \
  -U postgres \
  -d postgres \
  -v ON_ERROR_STOP=1 \
  2>&1 | tail -20

echo "Restore complete. Restarting backend to reload catalog..."
docker compose restart backend 2>/dev/null || echo "Backend not in docker-compose — restart manually."

source "$(dirname "$0")/reload_catalog.sh" 2>/dev/null || true
echo "Done."

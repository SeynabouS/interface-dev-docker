#!/bin/bash
set -euo pipefail

BACKUP_FILE="/import/gracethd.backup"
DB_NAME="${POSTGRES_DB:-postgres}"
DB_USER="${POSTGRES_USER:-postgres}"
export PGPASSWORD="${POSTGRES_PASSWORD:-}"

if [ ! -f "$BACKUP_FILE" ]; then
  echo "No backup found at $BACKUP_FILE, skipping restore."
  exit 0
fi

echo "Restoring $BACKUP_FILE into $DB_NAME..."
pg_restore --clean --if-exists --no-owner --role="$DB_USER" --dbname="$DB_NAME" "$BACKUP_FILE"
echo "Restore finished."

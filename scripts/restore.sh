#!/usr/bin/env bash
set -euo pipefail
# Restore a backup that you've placed into ./db/import on your host.

FILE="${1:-}"
if [ -z "$FILE" ]; then
  echo "Usage: scripts/restore.sh <filename inside ./db/import>"
  exit 1
fi
if [ ! -f "./db/import/$FILE" ]; then
  echo "File ./db/import/$FILE not found. Place your dump into ./db/import first."
  exit 1
fi

# Default vars if not set in your shell
DB_USERNAME="${DB_USERNAME:-app}"
DB_NAME="${DB_NAME:-telecom_db}"

EXT="${FILE##*.}"
if [[ "$EXT" == "dump" ]]; then
  echo "[*] Restoring custom-format dump with pg_restore -> $FILE"
  docker compose exec -T db bash -lc "pg_restore -U $DB_USERNAME -d $DB_NAME --clean --if-exists /import/$FILE"
else
  echo "[*] Restoring plain SQL with psql -> $FILE"
  docker compose exec -T db bash -lc "psql -U $DB_USERNAME -d $DB_NAME -f /import/$FILE"
fi
echo '[✓] Restore completed.'

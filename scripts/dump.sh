#!/usr/bin/env bash
set -euo pipefail
# Dump the current running DB into ./db/import/backup.dump for safe-keeping.
# Usage:
#   scripts/dump.sh [output_name.dump]
OUT="${1:-backup.dump}"
DB_USERNAME="${DB_USERNAME:-app}"
DB_NAME="${DB_NAME:-telecom_db}"
echo "[*] Dumping database to ./db/import/$OUT ..."
docker compose exec -T db bash -lc "pg_dump -U $DB_USERNAME -d $DB_NAME -Fc -f /import/$OUT"
echo "[✓] Dump created at ./db/import/$OUT"

#!/usr/bin/env bash
# Restores the newest dump into a throwaway Postgres container and asserts it
# has rows. An untested backup is a hope, not a backup. Run monthly.
set -euo pipefail

cd "$(dirname "$0")"
# shellcheck disable=SC1091
set -a; source .env; set +a

BACKUP_DIR="${BACKUP_DIR:-/srv/backups}"
NEWEST="$(find "$BACKUP_DIR" -name 'tasks-*.dump' -printf '%T@ %p\n' \
          | sort -rn | head -1 | cut -d' ' -f2-)"

if [[ -z "${NEWEST:-}" ]]; then
    echo "FATAL: no dumps found in $BACKUP_DIR" >&2
    exit 1
fi
echo "verifying: $NEWEST"

CONTAINER="tasks-restore-check-$$"
cleanup() { docker rm -f "$CONTAINER" >/dev/null 2>&1 || true; }
trap cleanup EXIT

docker run -d --name "$CONTAINER" \
    -e POSTGRES_DB="$POSTGRES_DB" \
    -e POSTGRES_USER="$POSTGRES_USER" \
    -e POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
    postgres:17-alpine >/dev/null

until docker exec "$CONTAINER" pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1; do
    sleep 1
done

docker exec -i "$CONTAINER" pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner < "$NEWEST"

TABLES="$(docker exec "$CONTAINER" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc \
    "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")"
USERS="$(docker exec "$CONTAINER" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc \
    "SELECT count(*) FROM auth_user")"

echo "restored tables: $TABLES, auth_user rows: $USERS"
[[ "$TABLES" -gt 0 ]] || { echo "FATAL: restore produced no tables" >&2; exit 1; }
echo "restore check PASSED"

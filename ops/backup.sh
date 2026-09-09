#!/usr/bin/env bash
# Nightly Postgres dump. Invoked by the systemd timer and by deploy.sh.
set -euo pipefail

cd "$(dirname "$0")"
# shellcheck disable=SC1091
set -a; source .env; set +a

BACKUP_DIR="${BACKUP_DIR:-/srv/backups}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
TARGET="${BACKUP_DIR}/tasks-${STAMP}.dump"

mkdir -p "$BACKUP_DIR"

# -Fc (custom format): compressed, and pg_restore can do selective restores.
docker compose exec -T db \
    pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB" > "$TARGET"

# Fail loudly on a truncated dump rather than silently keeping a useless file.
if [[ ! -s "$TARGET" ]]; then
    echo "FATAL: dump is empty: $TARGET" >&2
    rm -f "$TARGET"
    exit 1
fi

echo "backup ok: $TARGET ($(du -h "$TARGET" | cut -f1))"

# Retention: 14 daily. Weeklies are kept by the off-box copy, not here.
find "$BACKUP_DIR" -name 'tasks-*.dump' -mtime +14 -delete

# TODO(ops): off-box copy. A backup on the same machine is not a backup.
#   restic -r <repo> backup "$BACKUP_DIR"
# or
#   rsync -a "$BACKUP_DIR/" laptop:/srv/tasks-backups/   # over Tailscale

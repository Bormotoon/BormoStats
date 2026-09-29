#!/usr/bin/env bash
# Back up the Docker stack: ClickHouse (native BACKUP), Redis (RDB snapshot) and
# Metabase (application DB volume). Archives are optionally GPG-encrypted and
# pruned after BACKUP_RETENTION_DAYS. Schedule it with cron/systemd timers, e.g.
#   15 2 * * * cd /opt/bormostats && make backup >> /var/log/bormostats-backup.log 2>&1
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT_DIR/.env"
COMPOSE_FILE="$ROOT_DIR/infra/docker/docker-compose.yml"
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

STACK_NAME="${STACK_NAME:-bormostats}"
BACKUP_DIR="${BACKUP_DIR:-$ROOT_DIR/backups}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
TARGET="$BACKUP_DIR/$STAMP"
compose() { docker compose --project-name "$STACK_NAME" --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"; }

mkdir -p "$TARGET"
chmod 700 "$BACKUP_DIR" "$TARGET"

echo "[1/4] ClickHouse BACKUP DATABASE ${CH_DB} -> File('/var/lib/clickhouse/backups/${STAMP}')"
compose exec -T -e CLICKHOUSE_PASSWORD="$BOOTSTRAP_CH_ADMIN_PASSWORD" clickhouse \
  clickhouse-client --user "$BOOTSTRAP_CH_ADMIN_USER" \
  --query "BACKUP DATABASE \`${CH_DB}\` TO File('/var/lib/clickhouse/backups/${STAMP}')"
compose exec -T clickhouse tar -C /var/lib/clickhouse/backups -cf - "$STAMP" > "$TARGET/clickhouse.tar"
compose exec -T clickhouse rm -rf "/var/lib/clickhouse/backups/${STAMP}"

echo "[2/4] Redis snapshot"
compose exec -T -e REDISCLI_AUTH="$REDIS_PASSWORD" redis \
  redis-cli --user "${REDIS_USERNAME:-bormostats}" --no-auth-warning SAVE >/dev/null
compose cp redis:/data/dump.rdb "$TARGET/redis-dump.rdb"

echo "[3/4] Metabase application database"
compose cp metabase:/metabase-data "$TARGET/metabase-data"

ARCHIVE="$BACKUP_DIR/bormostats-$STAMP.tar.gz"
tar -C "$BACKUP_DIR" -czf "$ARCHIVE" "$STAMP"
rm -rf "$TARGET"
if [[ -n "${BACKUP_GPG_RECIPIENT:-}" ]]; then
  gpg --batch --yes --encrypt --recipient "$BACKUP_GPG_RECIPIENT" --output "$ARCHIVE.gpg" "$ARCHIVE"
  rm -f "$ARCHIVE"
  ARCHIVE="$ARCHIVE.gpg"
fi
(cd "$(dirname "$ARCHIVE")" && sha256sum "$(basename "$ARCHIVE")" > "$(basename "$ARCHIVE").sha256")

echo "[4/4] Retention: removing archives older than ${RETENTION_DAYS} days"
find "$BACKUP_DIR" -maxdepth 1 -name 'bormostats-*.tar.gz*' -mtime "+${RETENTION_DAYS}" -print -delete

echo "Backup written: $ARCHIVE"

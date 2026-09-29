#!/usr/bin/env bash
# Restore drill: restore the newest ClickHouse backup into a scratch database,
# compare row counts with the live database and drop the scratch copy.
# Usage: scripts/restore_check.sh [archive]   (defaults to the newest archive)
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
compose() { docker compose --project-name "$STACK_NAME" --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"; }
ch() {
  compose exec -T -e CLICKHOUSE_PASSWORD="$BOOTSTRAP_CH_ADMIN_PASSWORD" clickhouse \
    clickhouse-client --user "$BOOTSTRAP_CH_ADMIN_USER" --query "$1"
}

ARCHIVE="${1:-}"
if [[ -z "$ARCHIVE" ]]; then
  for candidate in "$BACKUP_DIR"/bormostats-*.tar.gz "$BACKUP_DIR"/bormostats-*.tar.gz.gpg; do
    [[ -f "$candidate" ]] || continue
    if [[ -z "$ARCHIVE" || "$candidate" -nt "$ARCHIVE" ]]; then ARCHIVE="$candidate"; fi
  done
fi
[[ -n "$ARCHIVE" && -f "$ARCHIVE" ]] || { echo "No backup archive found in $BACKUP_DIR"; exit 1; }
if [[ -f "$ARCHIVE.sha256" ]]; then
  (cd "$(dirname "$ARCHIVE")" && sha256sum -c "$(basename "$ARCHIVE").sha256")
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
if [[ "$ARCHIVE" == *.gpg ]]; then
  gpg --batch --decrypt "$ARCHIVE" | tar -C "$WORK" -xzf -
else
  tar -C "$WORK" -xzf "$ARCHIVE"
fi
STAMP="$(ls "$WORK")"
SCRATCH_DB="${CH_DB}_restore_check"

compose exec -T clickhouse sh -c "rm -rf /var/lib/clickhouse/backups/$STAMP"
compose exec -T clickhouse tar -C /var/lib/clickhouse/backups -xf - < "$WORK/$STAMP/clickhouse.tar"
ch "DROP DATABASE IF EXISTS \`${SCRATCH_DB}\`"
ch "RESTORE DATABASE \`${CH_DB}\` AS \`${SCRATCH_DB}\` FROM File('/var/lib/clickhouse/backups/${STAMP}')"

echo "table,live_rows,restored_rows"
FAIL=0
for table in sys_schema_migrations dim_account dim_user mrt_sales_daily mrt_stock_daily; do
  live="$(ch "SELECT count() FROM \`${CH_DB}\`.\`${table}\`")"
  restored="$(ch "SELECT count() FROM \`${SCRATCH_DB}\`.\`${table}\`")"
  echo "${table},${live},${restored}"
  if [[ "$restored" -eq 0 && "$live" -gt 0 ]]; then FAIL=1; fi
done

ch "DROP DATABASE IF EXISTS \`${SCRATCH_DB}\`"
compose exec -T clickhouse rm -rf "/var/lib/clickhouse/backups/${STAMP}"
if [[ "$FAIL" -ne 0 ]]; then
  echo "Restore check FAILED: restored tables are empty"
  exit 1
fi
echo "Restore check passed for $(basename "$ARCHIVE")"

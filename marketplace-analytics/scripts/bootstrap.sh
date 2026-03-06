#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT_DIR/.env"
COMPOSE_FILE="$ROOT_DIR/infra/docker/docker-compose.yml"
PYTHON_BIN="python3"

if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
  PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
fi

compose_cmd() {
  docker compose --project-name "$STACK_NAME" --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

wait_for_service() {
  local service="$1"
  local timeout_seconds="$2"
  local started_at now container_id status

  started_at="$(date +%s)"
  while true; do
    container_id="$(compose_cmd ps -q "$service" || true)"
    if [[ -n "$container_id" ]]; then
      status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container_id")"
      if [[ "$status" == "healthy" || "$status" == "running" ]]; then
        echo "Service '$service' is $status"
        return 0
      fi
    fi

    now="$(date +%s)"
    if (( now - started_at >= timeout_seconds )); then
      echo "Timed out waiting for service '$service' health"
      compose_cmd ps
      return 1
    fi
    sleep 2
  done
}

check_host_port_conflict() {
  local host_port="$1"
  local service_name="$2"
  local conflicts=()
  local name ports project

  while IFS=$'\t' read -r name ports; do
    [[ -z "$name" ]] && continue
    [[ "$ports" == *":${host_port}->"* ]] || continue

    project="$(docker inspect --format '{{ index .Config.Labels "com.docker.compose.project" }}' "$name" 2>/dev/null || true)"
    if [[ "$project" == "$STACK_NAME" ]]; then
      continue
    fi
    conflicts+=("$name [$ports]")
  done < <(docker ps --format '{{.Names}}\t{{.Ports}}')

  if (( ${#conflicts[@]} > 0 )); then
    echo "Host port ${host_port} for ${service_name} is already used by:"
    printf ' - %s\n' "${conflicts[@]}"
    echo "Pick another port in .env and retry."
    return 1
  fi
}

if [[ ! -f "$ENV_FILE" ]]; then
  cp "$ROOT_DIR/.env.example" "$ENV_FILE"
  echo "Created $ENV_FILE from .env.example"
  echo "Populate required secrets in $ENV_FILE and rerun bootstrap."
  exit 1
fi

set -a
source "$ENV_FILE"
set +a

STACK_NAME="${STACK_NAME:-bormostats}"
BACKEND_HOST_PORT="${BACKEND_HOST_PORT:-18080}"
METABASE_HOST_PORT="${METABASE_HOST_PORT:-13000}"
BOOTSTRAP_CH_HOST="${BOOTSTRAP_CH_HOST:-localhost}"
BOOTSTRAP_CH_PORT="${BOOTSTRAP_CH_PORT:-${CH_HTTP_HOST_PORT:-18123}}"
BOOTSTRAP_CH_ADMIN_USER="${BOOTSTRAP_CH_ADMIN_USER:-default}"
BOOTSTRAP_CH_ADMIN_PASSWORD="${BOOTSTRAP_CH_ADMIN_PASSWORD:-}"

check_host_port_conflict "$BACKEND_HOST_PORT" "backend"
check_host_port_conflict "$METABASE_HOST_PORT" "metabase"
check_host_port_conflict "$BOOTSTRAP_CH_PORT" "clickhouse-http"

run_python_with_bootstrap_admin_ch() {
  APP_CH_USER="$CH_USER" \
  APP_CH_PASSWORD="$CH_PASSWORD" \
  APP_CH_DB="$CH_DB" \
  APP_CH_RO_USER="${CH_RO_USER:-}" \
  APP_CH_RO_PASSWORD="${CH_RO_PASSWORD:-}" \
  CH_HOST="$BOOTSTRAP_CH_HOST" \
  CH_PORT="$BOOTSTRAP_CH_PORT" \
  CH_USER="$BOOTSTRAP_CH_ADMIN_USER" \
  CH_PASSWORD="$BOOTSTRAP_CH_ADMIN_PASSWORD" \
  "$PYTHON_BIN" "$@"
}

run_python_with_app_ch() {
  CH_HOST="$BOOTSTRAP_CH_HOST" \
  CH_PORT="$BOOTSTRAP_CH_PORT" \
  CH_USER="$CH_USER" \
  CH_PASSWORD="$CH_PASSWORD" \
  "$PYTHON_BIN" "$@"
}

echo "Validating required secrets and runtime config..."
"$PYTHON_BIN" "$ROOT_DIR/scripts/check_tokens.py" --skip-api

echo "Starting infrastructure services..."
if ! compose_cmd up -d --build clickhouse redis; then
  echo "docker compose build failed; retrying with classic builder fallback..."
  COMPOSE_DOCKER_CLI_BUILD=0 DOCKER_BUILDKIT=0 compose_cmd up -d --build clickhouse redis || compose_cmd up -d clickhouse redis
fi

wait_for_service clickhouse 180
wait_for_service redis 120

echo "Provisioning ClickHouse application users..."
run_python_with_bootstrap_admin_ch - <<'PY'
import os
import re

import clickhouse_connect

identifier_pattern = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
db_name = os.getenv("APP_CH_DB", "mp_analytics")
app_user = os.getenv("APP_CH_USER", "")
app_password = os.getenv("APP_CH_PASSWORD", "")
ro_user = os.getenv("APP_CH_RO_USER", "")
ro_password = os.getenv("APP_CH_RO_PASSWORD", "")

for label, value in {
    "APP_CH_DB": db_name,
    "APP_CH_USER": app_user,
}.items():
    if not identifier_pattern.fullmatch(value):
        raise SystemExit(f"Invalid {label} identifier: {value}")

client = clickhouse_connect.get_client(
    host=os.getenv("CH_HOST", "localhost"),
    port=int(os.getenv("CH_PORT", "8123")),
    username=os.getenv("CH_USER", "default"),
    password=os.getenv("CH_PASSWORD", ""),
    database="default",
)
try:
    quoted_db = f"`{db_name}`"
    quoted_app_user = f"`{app_user}`"
    client.command(f"CREATE DATABASE IF NOT EXISTS {quoted_db}")
    client.command(
        f"CREATE USER IF NOT EXISTS {quoted_app_user} IDENTIFIED WITH plaintext_password BY %(password)s",
        parameters={"password": app_password},
    )
    client.command(f"GRANT ALL ON {quoted_db}.* TO {quoted_app_user}")

    if ro_user or ro_password:
        if not identifier_pattern.fullmatch(ro_user):
            raise SystemExit(f"Invalid APP_CH_RO_USER identifier: {ro_user}")
        quoted_ro_user = f"`{ro_user}`"
        client.command(
            f"CREATE USER IF NOT EXISTS {quoted_ro_user} IDENTIFIED WITH plaintext_password BY %(password)s",
            parameters={"password": ro_password},
        )
        client.command(f"GRANT SELECT ON {quoted_db}.* TO {quoted_ro_user}")
finally:
    client.close()
PY

echo "Applying ClickHouse migrations..."
cd "$ROOT_DIR"
echo "Using bootstrap ClickHouse endpoint: ${BOOTSTRAP_CH_HOST}:${BOOTSTRAP_CH_PORT}"
run_python_with_app_ch warehouse/apply_migrations.py

echo "Checking required warehouse tables..."
CH_HOST="$BOOTSTRAP_CH_HOST" CH_PORT="$BOOTSTRAP_CH_PORT" CH_USER="$CH_USER" CH_PASSWORD="$CH_PASSWORD" "$PYTHON_BIN" - <<'PY'
import os
import sys

import clickhouse_connect

required_tables = {
    "sys_watermarks",
    "sys_task_runs",
    "dim_marketplace",
    "dim_account",
    "dim_product",
}

client = clickhouse_connect.get_client(
    host=os.getenv("CH_HOST", "localhost"),
    port=int(os.getenv("CH_PORT", "8123")),
    username=os.getenv("CH_USER", "default"),
    password=os.getenv("CH_PASSWORD", ""),
    database=os.getenv("CH_DB", "mp_analytics"),
)
try:
    rows = client.query(
        """
        SELECT name
        FROM system.tables
        WHERE database = %(database)s
          AND name IN %(names)s
        """,
        parameters={
            "database": os.getenv("CH_DB", "mp_analytics"),
            "names": tuple(sorted(required_tables)),
        },
    ).result_rows
    existing = {str(row[0]) for row in rows}
    missing = sorted(required_tables - existing)
    if missing:
        print(f"Missing required tables: {missing}")
        raise SystemExit(1)
    print("Warehouse schema checks passed.")
finally:
    client.close()
PY

echo "Starting application services..."
if ! compose_cmd up -d --build backend worker beat metabase; then
  echo "docker compose build failed; retrying with classic builder fallback..."
  COMPOSE_DOCKER_CLI_BUILD=0 DOCKER_BUILDKIT=0 compose_cmd up -d --build backend worker beat metabase || compose_cmd up -d backend worker beat metabase
fi

wait_for_service backend 180

echo "Running API token smoke checks..."
if [[ "${BOOTSTRAP_SKIP_TOKEN_CHECKS:-0}" == "1" ]]; then
  echo "Skipping outbound API smoke checks because BOOTSTRAP_SKIP_TOKEN_CHECKS=1."
else
  "$PYTHON_BIN" "$ROOT_DIR/scripts/check_tokens.py"
fi

echo "Running backend health checks..."
"$PYTHON_BIN" - <<'PY'
import json
import os
import time
import urllib.request
from urllib.error import URLError


def check(url: str) -> None:
    attempts = 15
    delay_seconds = 2.0
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(url, timeout=15.0) as response:  # noqa: S310
                if response.status != 200:
                    raise RuntimeError(f"{url} returned status={response.status}")
                payload = json.loads(response.read().decode("utf-8"))
                print(f"{url} -> {payload}")
                return
        except (URLError, ConnectionError, RuntimeError) as exc:
            last_error = exc
            if attempt == attempts:
                break
            time.sleep(delay_seconds)
    raise RuntimeError(f"health check failed for {url}: {last_error}")


backend_port = os.getenv("BACKEND_HOST_PORT", "18080")
check(f"http://localhost:{backend_port}/health")
check(f"http://localhost:{backend_port}/ready")
PY

echo "Bootstrap finished successfully."

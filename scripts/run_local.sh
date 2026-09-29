#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT_DIR/.env"
COMPOSE_FILE="$ROOT_DIR/infra/docker/docker-compose.yml"
PYTHON_BIN="python3"
if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
  PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
fi

# 1. Create .env from the selected environment template if missing
if [[ ! -f "$ENV_FILE" ]]; then
  "$PYTHON_BIN" "$ROOT_DIR/scripts/init_env.py" --env "${ENV:-dev}" --output "$ENV_FILE" || true
  echo ">> Set WB_TOKEN_STATISTICS, WB_TOKEN_ANALYTICS, OZON_CLIENT_ID and OZON_API_KEY"
  echo ">> in $ENV_FILE, then run 'make up' again."
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

# 2. Generate TLS certs for nginx (required for proxy)
bash "$ROOT_DIR/scripts/gen_tls_cert.sh"

# 3. Build and start everything (paths are absolute, so the working directory does not matter)
echo "Starting BormoStats..."
docker compose \
  --project-name "${STACK_NAME:-bormostats}" \
  --env-file "$ENV_FILE" \
  -f "$COMPOSE_FILE" \
  up -d --build

echo ""
echo "================================================"
echo "  BormoStats is starting up"
echo "  UI:  https://${TLS_SERVER_NAME:-localhost}:${BACKEND_TLS_HOST_PORT:-18443}/ui/"
echo "  (http://localhost:${BACKEND_HOST_PORT:-18080} redirects to HTTPS)"
echo "================================================"

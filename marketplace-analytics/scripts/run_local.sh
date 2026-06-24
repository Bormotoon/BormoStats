#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# 1. Create .env from example if missing
if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example"
  echo ">> Edit .env and set your WB_API_KEY / OZON_API_KEY, then run this script again."
  echo ">> Minimal required: WB_STATISTICS_API_KEY, OZON_CLIENT_ID, OZON_API_KEY"
  exit 1
fi

set -a; source .env; set +a

# 2. Generate TLS certs for nginx (required for proxy)
mkdir -p infra/nginx/certs
if [ ! -s infra/nginx/certs/tls.crt ]; then
  openssl req -x509 -nodes -newkey rsa:2048 \
    -days "${TLS_CERT_DAYS:-365}" \
    -keyout infra/nginx/certs/tls.key \
    -out infra/nginx/certs/tls.crt \
    -subj "/CN=${TLS_SERVER_NAME:-localhost}" 2>/dev/null
  echo "Self-signed TLS cert generated"
fi

# 3. Build and start everything
echo "Starting BormoStats..."
cd infra/docker
docker compose --env-file ../../.env up -d --build

echo ""
echo "================================================"
echo "  BormoStats is starting up"
echo "  UI:  http://localhost:${BACKEND_HOST_PORT:-18080}/ui/"
echo "================================================"

#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/infra/docker/docker-compose.yml"
ENV_FILE="$ROOT_DIR/.env"
NGINX_CERT_DIR="$ROOT_DIR/infra/nginx/certs"

if [ ! -f "$ENV_FILE" ]; then
  cp "$ROOT_DIR/.env.example" "$ENV_FILE"
fi

set -a
source "$ENV_FILE"
set +a

mkdir -p "$NGINX_CERT_DIR"
if [ ! -s "$NGINX_CERT_DIR/tls.crt" ] || [ ! -s "$NGINX_CERT_DIR/tls.key" ]; then
  if ! command -v openssl >/dev/null 2>&1; then
    echo "openssl is required to generate TLS certs for the reverse proxy."
    exit 1
  fi
  openssl req \
    -x509 \
    -nodes \
    -newkey rsa:2048 \
    -days "${TLS_CERT_DAYS:-30}" \
    -keyout "$NGINX_CERT_DIR/tls.key" \
    -out "$NGINX_CERT_DIR/tls.crt" \
    -subj "/CN=${TLS_SERVER_NAME:-localhost}" >/dev/null 2>&1
fi

cd "$ROOT_DIR/infra/docker"
docker compose --env-file ../../.env -f docker-compose.yml up -d --build

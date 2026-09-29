#!/usr/bin/env bash
# Generate a self-signed certificate for the nginx proxy with proper SAN entries.
# For production, replace infra/nginx/certs/tls.{crt,key} with a trusted (ACME) certificate.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CERT_DIR="${NGINX_CERT_DIR:-$ROOT_DIR/infra/nginx/certs}"
SERVER_NAME="${TLS_SERVER_NAME:-localhost}"
CERT_DAYS="${TLS_CERT_DAYS:-30}"

mkdir -p "$CERT_DIR"
if [[ -s "$CERT_DIR/tls.crt" && -s "$CERT_DIR/tls.key" ]]; then
  exit 0
fi
if ! command -v openssl >/dev/null 2>&1; then
  echo "openssl is required to generate TLS certs for the reverse proxy." >&2
  exit 1
fi

SAN="DNS:${SERVER_NAME}"
if [[ "$SERVER_NAME" != "localhost" ]]; then
  SAN="${SAN},DNS:localhost"
fi
SAN="${SAN},IP:127.0.0.1,IP:::1"

echo "Generating self-signed TLS certificate for ${SERVER_NAME} (SAN: ${SAN})..."
openssl req -x509 -nodes -newkey rsa:2048 \
  -days "$CERT_DAYS" \
  -keyout "$CERT_DIR/tls.key" \
  -out "$CERT_DIR/tls.crt" \
  -subj "/CN=${SERVER_NAME}" \
  -addext "subjectAltName=${SAN}" >/dev/null 2>&1
chmod 600 "$CERT_DIR/tls.key"

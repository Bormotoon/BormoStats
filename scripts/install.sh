#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "=== BormoStats OS Installation ==="
echo ""

# 1. Check prerequisites
echo "[1/6] Checking prerequisites..."
command -v python3 >/dev/null 2>&1 || { echo "Error: python3 is required"; exit 1; }
python3 -c "import sys; assert sys.version_info >= (3, 14), 'Python 3.14+ required'" 2>/dev/null || {
  echo "Error: Python 3.14+ is required (found $(python3 --version 2>&1))"
  exit 1
}
command -v node >/dev/null 2>&1 || echo "Warning: node not found — frontend build will be skipped"
command -v npm >/dev/null 2>&1 || echo "Warning: npm not found — frontend build will be skipped"
echo "  OK"

# 2. Create .env if missing
echo "[2/6] Configuring environment..."
if [ ! -f .env ]; then
  cp .env.example .env
  echo "  Created .env from .env.example"
  echo "  >> Edit .env and set your API keys, then re-run this script."
  exit 1
fi
echo "  .env found"

# 3. Create virtualenv and install Python deps
echo "[3/6] Installing Python dependencies..."
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -r requirements.txt -q
echo "  Done"

# 4. Build frontend
echo "[4/6] Building frontend..."
if command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; then
  cd frontend
  npm ci --silent 2>/dev/null
  npm run build 2>/dev/null
  cd "$ROOT_DIR"
  mkdir -p backend/app/ui/dist
  cp -r frontend/dist/* backend/app/ui/dist/ 2>/dev/null || true
  cp frontend/favicon.svg backend/app/ui/dist/ 2>/dev/null || true
  echo "  Frontend built"
else
  echo "  Skipped (node/npm not available)"
fi

# 5. Apply migrations
echo "[5/6] Running database migrations..."
set -a
source .env
set +a
.venv/bin/python warehouse/apply_migrations.py && echo "  Migrations applied" || echo "  Warning: migrations failed (DB may not be ready)"

# 6. Print summary
echo ""
echo "[6/6] === Installation complete ==="
echo ""
echo "  Start services:"
echo "    make run              # Start all services in foreground"
echo "    make run-backend      # Start backend only"
echo "    make run-worker       # Start Celery worker"
echo "    make run-beat         # Start Celery beat"
echo ""
echo "  Or install systemd services:"
echo "    sudo make install-systemd"
echo ""
echo "  UI will be at:  http://localhost:${BACKEND_HOST_PORT:-18080}/ui/"
echo ""

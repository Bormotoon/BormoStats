#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [ ! -f .env ]; then
  echo "Error: .env file not found. Run 'make install' first."
  exit 1
fi

set -a
source .env
set +a

export PYTHONDONTWRITEBYTECODE=1
export PYTHONUNBUFFERED=1

VENV_PYTHON="$ROOT_DIR/.venv/bin/python"

cleanup() {
  echo ""
  echo "Shutting down..."
  kill $BACKEND_PID 2>/dev/null || true
  kill $WORKER_PID 2>/dev/null || true
  kill $BEAT_PID 2>/dev/null || true
  wait
  echo "All services stopped"
}

trap cleanup EXIT INT TERM

echo "=== BormoStats OS Run ==="
echo ""

# Start backend
echo "Starting backend (uvicorn)..."
PYTHONPATH="$ROOT_DIR/backend:$ROOT_DIR" \
  "$VENV_PYTHON" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

# Wait for backend to be ready
for i in {1..30}; do
  if curl -fsS http://127.0.0.1:8000/ready >/dev/null 2>&1; then
    echo "  Backend ready on http://0.0.0.0:8000"
    break
  fi
  if [ $i -eq 30 ]; then
    echo "  Warning: backend did not become ready"
  fi
  sleep 1
done

# Start Celery worker
echo "Starting Celery worker..."
PYTHONPATH="$ROOT_DIR/workers:$ROOT_DIR" \
  CELERY_METRICS_ROLE=worker \
  CELERY_METRICS_PORT=9101 \
  WORKER_PROMETHEUS_MULTIPROC_DIR=/tmp/bormostats-prometheus/worker \
  "$VENV_PYTHON" -m celery -A app.celery_app:celery_app worker --loglevel=INFO --concurrency=4 &
WORKER_PID=$!

# Start Celery beat
echo "Starting Celery beat..."
PYTHONPATH="$ROOT_DIR/workers:$ROOT_DIR" \
  CELERY_METRICS_ROLE=beat \
  CELERY_METRICS_PORT=9102 \
  "$VENV_PYTHON" -m celery -A app.celery_app:celery_app beat --loglevel=INFO --schedule=/tmp/celerybeat-schedule &
BEAT_PID=$!

echo ""
echo "=== All services started ==="
echo "  Backend: http://localhost:8000"
echo "  UI:      http://localhost:8000/ui/"
echo "  Worker:  metrics on :9101"
echo "  Beat:    metrics on :9102"
echo ""
echo "Press Ctrl+C to stop all services."

wait

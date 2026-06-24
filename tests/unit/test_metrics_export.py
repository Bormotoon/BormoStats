from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]
WORKERS_DIR = ROOT_DIR / "workers"
METRICS_EXPORT_PATH = WORKERS_DIR / "app" / "utils" / "metrics_export.py"

SPEC = importlib.util.spec_from_file_location("worker_metrics_export", METRICS_EXPORT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
worker_metrics_export: Any = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = worker_metrics_export
SPEC.loader.exec_module(worker_metrics_export)


def test_worker_metrics_payload_contains_expected_task_series(tmp_path: Path) -> None:
    env = {
        **os.environ,
        "PROMETHEUS_MULTIPROC_DIR": str(tmp_path),
        "WORKER_PROMETHEUS_MULTIPROC_DIR": str(tmp_path),
        "PYTHONPATH": os.pathsep.join([str(WORKERS_DIR), str(ROOT_DIR)]),
    }
    producer_code = """
from datetime import UTC, datetime, timedelta

from app.utils.metrics import observe_empty_payload, observe_task, observe_watermark

finished = datetime.now(UTC)
observe_task(
    "tasks.wb_collect.wb_sales_incremental",
    "success",
    finished - timedelta(seconds=2),
    finished,
)
observe_empty_payload("wb_sales")
observe_watermark("wb_sales", "acc-1", finished - timedelta(seconds=30))
"""
    subprocess.run([sys.executable, "-c", producer_code], env=env, check=True)

    consumer_code = """
from app.utils.metrics_export import generate_metrics_payload

print(generate_metrics_payload("worker").decode("utf-8"))
"""
    result = subprocess.run(
        [sys.executable, "-c", consumer_code],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    assert "task_duration_seconds" in result.stdout
    assert "task_runs_total" in result.stdout
    assert "watermark_lag_seconds" in result.stdout
    assert "empty_payload_total" in result.stdout


def test_beat_metrics_http_endpoint_serves_prometheus_payload() -> None:
    server_info = worker_metrics_export.start_metrics_http_server(
        "beat",
        host="127.0.0.1",
        port=0,
    )
    assert server_info is not None
    server, thread = server_info

    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{server.server_port}/metrics",
            timeout=5.0,
        ) as response:
            payload = response.read().decode("utf-8")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)
        worker_metrics_export._METRICS_SERVER = None

    assert "python_gc_objects_collected_total" in payload

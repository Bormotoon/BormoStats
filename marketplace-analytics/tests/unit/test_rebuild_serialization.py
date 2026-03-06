from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
WORKERS_DIR = ROOT_DIR / "workers"


def test_rebuild_jobs_are_serialized() -> None:
    script = """
import json
import threading

from app.tasks import marts, transforms


class FakeRedis:
    def __init__(self) -> None:
        self._values: dict[str, str] = {}
        self._guard = threading.Lock()

    def set(self, key: str, token: str, ex: int, nx: bool) -> bool:
        del ex, nx
        with self._guard:
            if key in self._values:
                return False
            self._values[key] = token
            return True

    def eval(self, script: str, count: int, key: str, token: str) -> int:
        del script, count
        with self._guard:
            if self._values.get(key) == token:
                del self._values[key]
                return 1
            return 0


class BlockingClient:
    def __init__(self, started: threading.Event, release: threading.Event) -> None:
        self.started = started
        self.release = release
        self.command_calls: list[str] = []
        self._blocked = False

    def command(self, sql: str) -> None:
        self.command_calls.append(sql)
        if not self._blocked:
            self._blocked = True
            self.started.set()
            if not self.release.wait(timeout=5):
                raise RuntimeError("transform release timeout")

    def close(self) -> None:
        return None


class RecordingClient:
    def __init__(self) -> None:
        self.command_calls: list[str] = []

    def command(self, sql: str) -> None:
        self.command_calls.append(sql)

    def close(self) -> None:
        return None


logs: list[dict[str, str]] = []


def fake_log_task_run(
    client,
    task_name,
    run_id,
    started_at,
    status,
    rows_ingested,
    message,
    meta=None,
):
    del client, run_id, started_at, rows_ingested, meta
    logs.append({"task_name": task_name, "status": status, "message": message})


shared_redis = FakeRedis()
transform_started = threading.Event()
allow_transform_finish = threading.Event()
transform_client = BlockingClient(transform_started, allow_transform_finish)
marts_client = RecordingClient()

transforms.get_redis_client = lambda: shared_redis
marts.get_redis_client = lambda: shared_redis
transforms.get_ch_client = lambda: transform_client
marts.get_ch_client = lambda: marts_client
transforms.log_task_run = fake_log_task_run
marts.log_task_run = fake_log_task_run

results: dict[str, object] = {}


def run_transform() -> None:
    results["transform"] = transforms.transform_all_recent()


worker = threading.Thread(target=run_transform)
worker.start()
if not transform_started.wait(timeout=5):
    raise RuntimeError("transform did not start")

results["marts"] = marts.build_marts_recent()
allow_transform_finish.set()
worker.join(timeout=5)
if worker.is_alive():
    raise RuntimeError("transform thread did not finish")

print(
    json.dumps(
        {
            "transform": results["transform"],
            "marts": results["marts"],
            "marts_commands": marts_client.command_calls,
            "logs": logs,
        }
    )
)
"""

    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join([str(WORKERS_DIR), str(ROOT_DIR)]),
    }
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["transform"]["status"] == "success"
    assert payload["marts"]["status"] == "skipped"
    assert payload["marts"]["reason"] == "lock_not_acquired"
    assert payload["marts_commands"] == []
    assert any(
        log["task_name"] == "tasks.marts.build_marts_recent" and log["status"] == "skipped"
        for log in payload["logs"]
    )


def test_rebuild_schedule_staggers_transform_and_marts() -> None:
    script = """
import json

from app.beat_schedule import beat_schedule

print(
    json.dumps(
        {
            "transform": beat_schedule["transform_raw_to_stg"]["schedule"]._orig_minute,
            "marts_recent": beat_schedule["build_marts_recent"]["schedule"]._orig_minute,
            "marts_backfill": beat_schedule["build_marts_backfill_14d"]["schedule"]._orig_minute,
        }
    )
)
"""

    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join([str(WORKERS_DIR), str(ROOT_DIR)]),
    }
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload == {
        "transform": "5,35",
        "marts_recent": "20,50",
        "marts_backfill": "20",
    }

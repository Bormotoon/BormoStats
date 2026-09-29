"""Run the worker test suite in its own interpreter (see tests/conftest.py)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]


def test_worker_suite_passes() -> None:
    env = {
        **os.environ,
        "BORMOSTATS_TEST_TARGET": "workers",
        "PYTHONPATH": os.pathsep.join([str(ROOT_DIR / "workers"), str(ROOT_DIR)]),
    }
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/worker_suite"],
        cwd=ROOT_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout[-6000:] + result.stderr[-3000:]

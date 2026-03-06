"""Prometheus metrics export helpers for Celery worker and beat processes."""

from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Sequence
from pathlib import Path
from threading import Thread
from typing import Literal, cast
from wsgiref.simple_server import WSGIServer

from prometheus_client import (
    REGISTRY,
    CollectorRegistry,
    generate_latest,
    multiprocess,
    start_http_server,
)

MetricsRole = Literal["worker", "beat"]

DEFAULT_METRICS_HOST = "0.0.0.0"
DEFAULT_WORKER_METRICS_PORT = 9101
DEFAULT_BEAT_METRICS_PORT = 9102
DEFAULT_WORKER_MULTIPROC_DIR = "/tmp/marketplace-analytics-prometheus/worker"

_METRICS_SERVER: tuple[WSGIServer, Thread] | None = None


def detect_metrics_role(argv: Sequence[str] | None = None) -> MetricsRole | None:
    configured_role = os.getenv("CELERY_METRICS_ROLE", "").strip().lower()
    if configured_role in {"worker", "beat"}:
        return cast(MetricsRole, configured_role)

    args = argv if argv is not None else sys.argv[1:]
    for arg in args:
        normalized = arg.strip().lower()
        if normalized in {"worker", "beat"}:
            return cast(MetricsRole, normalized)
    return None


def configure_metrics_runtime(role: MetricsRole | None) -> None:
    if role != "worker":
        os.environ.pop("PROMETHEUS_MULTIPROC_DIR", None)
        return

    multiproc_dir = _worker_multiproc_dir()
    os.environ["PROMETHEUS_MULTIPROC_DIR"] = str(multiproc_dir)
    multiproc_dir.mkdir(parents=True, exist_ok=True)
    for child in multiproc_dir.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def generate_metrics_payload(role: MetricsRole | None) -> bytes:
    return generate_latest(_metrics_registry(role))


def start_metrics_http_server(
    role: MetricsRole | None,
    *,
    host: str | None = None,
    port: int | None = None,
) -> tuple[WSGIServer, Thread] | None:
    if role is None or not _metrics_enabled():
        return None

    global _METRICS_SERVER
    if _METRICS_SERVER is not None:
        return _METRICS_SERVER

    _METRICS_SERVER = start_http_server(
        port=port if port is not None else _metrics_port(role),
        addr=host if host is not None else os.getenv("CELERY_METRICS_HOST", DEFAULT_METRICS_HOST),
        registry=_metrics_registry(role),
    )
    return _METRICS_SERVER


def mark_worker_process_dead(pid: int | None) -> None:
    if pid is None:
        return
    multiproc_dir = os.getenv("PROMETHEUS_MULTIPROC_DIR", "").strip()
    if not multiproc_dir:
        return
    multiprocess.mark_process_dead(pid, path=multiproc_dir)  # type: ignore[no-untyped-call]


def _metrics_enabled() -> bool:
    return os.getenv("CELERY_METRICS_ENABLED", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _metrics_port(role: MetricsRole) -> int:
    default_port = DEFAULT_WORKER_METRICS_PORT if role == "worker" else DEFAULT_BEAT_METRICS_PORT
    return int(os.getenv("CELERY_METRICS_PORT", str(default_port)))


def _metrics_registry(role: MetricsRole | None) -> CollectorRegistry:
    if role == "worker":
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(  # type: ignore[no-untyped-call]
            registry,
            path=str(_worker_multiproc_dir()),
        )
        return registry
    return REGISTRY


def _worker_multiproc_dir() -> Path:
    raw = os.getenv("WORKER_PROMETHEUS_MULTIPROC_DIR", DEFAULT_WORKER_MULTIPROC_DIR)
    return Path(raw).resolve()

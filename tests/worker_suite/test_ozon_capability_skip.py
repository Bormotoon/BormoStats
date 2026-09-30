from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from app.tasks import ozon_collect


def _status_error(status: int, body: str) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://api-seller.ozon.ru/v3/finance/transaction/list")
    return httpx.HTTPStatusError(
        "error", request=request, response=httpx.Response(status, text=body, request=request)
    )


def test_skip_records_status_path_and_body(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[Any, ...]] = []
    monkeypatch.setattr(ozon_collect, "log_task_run", lambda *a, **kw: calls.append((a, kw)))

    ozon_collect._log_capability_skip(
        object(),
        "tasks.x",
        "run",
        datetime.now(UTC),
        "finance",
        _status_error(403, '{"code": 7,\n "message": "Forbidden"}'),
    )

    args, kwargs = calls[0]
    assert args[4] == "skipped"
    assert "403 POST /v3/finance/transaction/list" in args[6]
    assert "Forbidden" in args[6]
    assert kwargs["meta"]["error"] == args[6].split(": ", 1)[1]


def test_detail_truncates_long_bodies() -> None:
    detail = ozon_collect._capability_detail(_status_error(403, "x" * 5000))
    assert len(detail) < 400

"""Historical Performance API reports: only explicit SKU rows are attributable."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

TERMINAL_FAILURE_STATES = frozenset({"FAILED", "ERROR", "CANCELLED", "NOT_FOUND"})


def report_is_fresh(updated_at: datetime, today: date) -> bool:
    """Reuse a completed report within one Moscow day; refresh later corrections."""
    stamp = updated_at if updated_at.tzinfo else updated_at.replace(tzinfo=UTC)
    return stamp.astimezone(ZoneInfo("Europe/Moscow")).date() == today


def decimal_value(value: Any) -> Decimal:
    value_str = str(value or "0").replace("\u00a0", "").replace(" ", "").replace(",", ".")
    result = Decimal(value_str)
    if not result.is_finite():
        raise ValueError("Invalid Performance cost")
    return result


def parse_report(
    data: dict[str, Any], campaigns: list[str], start: date, stop: date
) -> dict[tuple[date, str, str], Decimal]:
    result: dict[tuple[date, str, str], Decimal] = {}
    for campaign in campaigns:
        block = data.get(str(campaign))
        if not isinstance(block, dict) or not isinstance(block.get("report"), dict):
            raise ValueError(f"Performance report missing campaign {campaign}")
        report = block["report"]
        rows = report.get("rows")
        if not isinstance(rows, list):
            raise ValueError("Performance report rows are missing")
        known = Decimal(0)
        for row in rows:
            raw_sku = str(row.get("sku") or "")
            if not raw_sku.isdigit() or int(raw_sku) <= 0:
                continue
            day = datetime.strptime(row["date"], "%d.%m.%Y").date()
            if not start <= day <= stop:
                raise ValueError("Performance report returned a date outside its period")
            amount = decimal_value(row.get("moneySpent"))
            key = (day, str(campaign), raw_sku)
            result[key] = result.get(key, Decimal(0)) + amount
            known += amount
        # Daily SKU rows and campaign totals can differ after corrections, not only
        # rounding (observed in real 2025 reports). Keep explicit SKU rows unchanged.
        # Finance-versus-SKU differences remain on the unmatched expense article.
    return result


def cache_key(account: str, campaigns: list[str], start: date, stop: date) -> str:
    parts = [account, start.isoformat(), stop.isoformat(), *sorted(campaigns)]
    return hashlib.sha256(("|".join(parts)).encode()).hexdigest()


def load_active_job(
    ch: Any, account_id: str, report_kind: str, period_key: str
) -> dict[str, Any] | None:
    """Return the latest non-failed job for the period, or None if a new UUID is needed."""
    rows = ch.query(
        "SELECT job_uuid, status, payload FROM sys_ozon_report_jobs FINAL"
        " WHERE account_id = {aid:String} AND report_kind = {kind:String}"
        " AND period_key = {pkey:String}"
        " AND status NOT IN ('failed', 'cancelled')"
        " ORDER BY updated_at DESC LIMIT 1",
        parameters={"aid": account_id, "kind": report_kind, "pkey": period_key},
    ).named_results()
    return next(iter(rows), None)


def save_job_state(
    ch: Any,
    *,
    account_id: str,
    report_kind: str,
    period_key: str,
    job_uuid: str,
    status: str,
    payload: str = "",
    error: str = "",
) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    ch.insert(
        "sys_ozon_report_jobs",
        [[account_id, report_kind, period_key, job_uuid, status, error[:500], payload, now, now]],
        column_names=[
            "account_id",
            "report_kind",
            "period_key",
            "job_uuid",
            "status",
            "error",
            "payload",
            "created_at",
            "updated_at",
        ],
    )


def fetch_report(
    client: Any,
    campaigns: list[str],
    start: date,
    stop: date,
    job_uuid: str | None = None,
    on_created: Callable[[str], None] | None = None,
    ch: Any = None,
    account_id: str = "",
    report_kind: str = "sku_ads",
    period_key: str = "",
    on_failed: Callable[[str, str], None] | None = None,
    poll_interval: float = 5.0,
    timeout: float = 600.0,
) -> tuple[dict[tuple[date, str, str], Decimal], str, dict[str, Any]]:
    headers = {"Authorization": "Bearer " + client._access_token(), "Accept": "application/json"}
    uuid = job_uuid
    pkey = period_key or cache_key(account_id, campaigns, start, stop)
    if not uuid:
        job = client.http.post(
            "/api/client/statistics/json",
            headers=headers,
            json={
                "campaigns": campaigns,
                "dateFrom": start.isoformat(),
                "dateTo": stop.isoformat(),
                "groupBy": "DATE",
            },
        )
        uuid = job.get("UUID") if isinstance(job, dict) else None
    if not uuid:
        raise ValueError("Performance did not return a report UUID")
    if ch is not None:
        save_job_state(
            ch,
            account_id=account_id,
            report_kind=report_kind,
            period_key=pkey,
            job_uuid=uuid,
            status="pending",
        )
    if on_created:
        on_created(uuid)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state_response = client._get("/api/client/statistics/" + uuid, {})
        state_val = state_response.get("state") if isinstance(state_response, dict) else ""
        state_upper = str(state_val or "").upper()
        if state_upper == "OK":
            data = client._get("/api/client/statistics/report", {"UUID": uuid})
            if ch is not None:
                save_job_state(
                    ch,
                    account_id=account_id,
                    report_kind=report_kind,
                    period_key=pkey,
                    job_uuid=uuid,
                    status="completed",
                )
            return parse_report(data, campaigns, start, stop), uuid, data
        if state_upper in TERMINAL_FAILURE_STATES:
            err_msg = str(
                (state_response.get("error") if isinstance(state_response, dict) else None)
                or state_val
                or "unknown error"
            )
            if ch is not None:
                save_job_state(
                    ch,
                    account_id=account_id,
                    report_kind=report_kind,
                    period_key=pkey,
                    job_uuid=uuid,
                    status="failed",
                    error=err_msg,
                )
            if on_failed:
                on_failed(uuid, err_msg)
            raise RuntimeError(f"Performance report generation failed: {err_msg}")
        time.sleep(poll_interval)
    raise TimeoutError("Performance report not ready within 10 minutes")

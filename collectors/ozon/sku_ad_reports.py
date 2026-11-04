"""Historical Performance API reports: only explicit SKU rows are attributable."""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

TERMINAL_FAILURE_STATES = frozenset({"FAILED", "ERROR", "CANCELLED", "NOT_FOUND"})
_UUID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def _validate_report_uuid(uuid: str) -> str:
    cleaned = str(uuid).strip()
    if not _UUID_RE.match(cleaned):
        raise ValueError(f"Invalid Ozon Performance report UUID: {uuid!r}")
    return cleaned


def check_sku_report_status(client: Any, uuid: str) -> dict[str, Any]:
    safe_uuid = _validate_report_uuid(uuid)
    res = client._get("/api/client/statistics/" + safe_uuid, {})
    return res if isinstance(res, dict) else {}


def download_sku_report(client: Any, uuid: str) -> dict[str, Any]:
    safe_uuid = _validate_report_uuid(uuid)
    res = client._get("/api/client/statistics/report", {"UUID": safe_uuid})
    return res if isinstance(res, dict) else {}


def group_campaigns_into_batches(
    campaign_ids: list[str], batch_size: int = 10
) -> list[list[str]]:
    return [campaign_ids[i : i + batch_size] for i in range(0, len(campaign_ids), batch_size)]


def request_sku_report(client: Any, campaigns: list[str], start: date, stop: date) -> str:
    headers = {"Authorization": "Bearer " + client._access_token(), "Accept": "application/json"}
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
    return _validate_report_uuid(uuid)


def parse_sku_report_payload(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten Ozon Performance report structure into row dictionaries."""
    rows: list[dict[str, Any]] = []
    for campaign_id, block in data.items():
        if not isinstance(block, dict):
            continue
        report = block.get("report")
        if not isinstance(report, dict):
            continue
        for row in report.get("rows") or []:
            if not isinstance(row, dict):
                continue
            sku_raw = str(row.get("sku") or "")
            if not sku_raw.isdigit() or int(sku_raw) <= 0:
                continue
            rows.append({**row, "campaign_id": str(campaign_id), "sku": int(sku_raw)})
    return rows


def rows_to_clickhouse_tuples(
    rows: list[dict[str, Any]],
    *,
    run_id: str,
    account_id: str,
) -> list[tuple[Any, ...]]:
    """Convert parsed rows to tuples matching raw_ozon_sku_ad_reports schema."""
    tuples: list[tuple[Any, ...]] = []
    for r in rows:
        day_raw = r.get("date")
        if isinstance(day_raw, str):
            try:
                day = datetime.strptime(day_raw, "%d.%m.%Y").date()
            except ValueError:
                day = date.fromisoformat(day_raw[:10])
        elif isinstance(day_raw, (date, datetime)):
            day = day_raw if isinstance(day_raw, date) else day_raw.date()
        else:
            continue
        sku = int(r.get("sku") or 0)
        if sku <= 0:
            continue
        cost = float(decimal_value(r.get("moneySpent") or r.get("cost") or 0))
        impressions = int(r.get("views") or r.get("impressions") or 0)
        clicks = int(r.get("clicks") or 0)
        orders = int(r.get("orders") or 0)
        revenue = float(decimal_value(r.get("orders_money") or r.get("revenue") or 0))
        tuples.append(
            (
                run_id,
                account_id,
                day,
                str(r.get("campaign_id") or ""),
                sku,
                str(r.get("offer_id") or ""),
                str(r.get("title") or ""),
                impressions,
                clicks,
                cost,
                orders,
                revenue,
                json.dumps(r, ensure_ascii=False),
            )
        )
    return tuples


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
    uuid = _validate_report_uuid(uuid)
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
        state_response = check_sku_report_status(client, uuid)
        state_val = state_response.get("state") if isinstance(state_response, dict) else ""
        state_upper = str(state_val or "").upper()
        if state_upper == "OK":
            data = download_sku_report(client, uuid)
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

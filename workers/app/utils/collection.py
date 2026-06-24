"""Shared abstractions for marketplace data collection tasks."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from app.utils.locking import LockNotAcquiredError, lock_scope
from app.utils.metrics import observe_empty_payload, observe_rows
from app.utils.runtime import get_ch_client, get_redis_client, log_task_run, new_run_context
from app.utils.watermarks import get_watermark, set_watermark


def _extract_columns(columns: list[str], rows: list[dict[str, Any]]) -> list[list[Any]]:
    return [[row.get(col) for col in columns] for row in rows]


def insert_rows(client: Any, table: str, columns: list[str], rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    data = _extract_columns(columns, rows)
    client.insert(table=table, data=data, column_names=columns)
    observe_rows(table=table, rows=len(rows))
    return len(rows)


def collect_incremental(
    *,
    task_name: str,
    source: str,
    account_id: str,
    lock_ttl_seconds: int = 1200,
    fetch_fn: Callable[..., list[dict[str, Any]]],
    parse_fn: Callable[..., Any],
    columns: list[str],
    table: str,
    watermark_fn: Callable[..., datetime] | None = None,
    watermark_start: datetime | None = None,
) -> dict[str, Any]:
    run_id, started_at = new_run_context()
    redis_client = get_redis_client()
    with lock_scope(
        redis_client=redis_client,
        source=source,
        account_id=account_id,
        ttl_seconds=lock_ttl_seconds,
        auto_renew=True,
    ):
        ch_client = get_ch_client()
        try:
            watermark = watermark_start or get_watermark(ch_client, source, account_id)
            records = fetch_fn(watermark)
            rows = parse_fn(records, run_id=run_id, account_id=account_id)
            if not rows:
                observe_empty_payload(source)
            inserted = insert_rows(ch_client, table, columns, rows)

            if watermark_fn:
                latest_ts = watermark_fn(rows)
            else:
                latest_ts = max(
                    (row.get("last_change_ts", row.get("operation_ts", watermark)) for row in rows),
                    default=watermark.replace(tzinfo=None),
                )
            if inserted > 0:
                set_watermark(ch_client, source, account_id, latest_ts.replace(tzinfo=UTC))

            log_task_run(
                ch_client,
                task_name,
                run_id,
                started_at,
                "success",
                inserted,
                f"{source} collected",
            )
            return {"status": "success", "rows": inserted, "watermark": str(latest_ts)}
        except Exception as exc:
            log_task_run(ch_client, task_name, run_id, started_at, "failed", 0, str(exc))
            raise


def wrap_task(
    fn: Callable[..., dict[str, Any]],
    **kwargs: Any,
) -> dict[str, Any]:
    try:
        return fn(**kwargs)
    except LockNotAcquiredError:
        return {"status": "skipped", "reason": "lock_not_acquired"}


def collect_backfill(
    *,
    task_name: str,
    source: str,
    account_id: str,
    days: int,
    max_days: int = 90,
    lock_ttl_seconds: int = 1800,
    fetch_day_fn: Callable[..., list[dict[str, Any]]],
    parse_fn: Callable[..., Any],
    columns: list[str],
    table: str,
    chunk_days: int = 1,
) -> dict[str, Any]:
    safe_days = max(1, min(days, max_days))
    run_id, started_at = new_run_context()
    now_day = datetime.now(UTC).date()
    start_day = now_day - timedelta(days=safe_days)
    total_rows = 0

    ch_client = get_ch_client()
    redis_client = get_redis_client()

    try:
        with lock_scope(
            redis_client=redis_client,
            source=source,
            account_id=account_id,
            ttl_seconds=lock_ttl_seconds,
            auto_renew=True,
        ) as lock:
            from app.utils.chunking import date_chunks

            for day_cursor, _ in date_chunks(start_day, now_day, chunk_days=chunk_days):
                lock.ensure_held()
                records = fetch_day_fn(day_cursor)
                rows = parse_fn(records, run_id=run_id, account_id=account_id)
                if not rows:
                    observe_empty_payload(source)
                total_rows += insert_rows(ch_client, table, columns, rows)

        log_task_run(
            ch_client,
            task_name,
            run_id,
            started_at,
            "success",
            total_rows,
            f"{source} backfill ({safe_days} days)",
        )
        return {"status": "success", "rows": total_rows, "days": safe_days}
    except LockNotAcquiredError:
        return {"status": "skipped", "reason": "lock_not_acquired"}
    except Exception as exc:
        log_task_run(ch_client, task_name, run_id, started_at, "failed", total_rows, str(exc))
        raise


def collect_snapshot(
    *,
    task_name: str,
    source: str,
    account_id: str,
    lock_ttl_seconds: int = 900,
    fetch_fn: Callable[..., list[dict[str, Any]]],
    parse_fn: Callable[..., Any],
    columns: list[str],
    table: str,
) -> dict[str, Any]:
    run_id, started_at = new_run_context()
    snapshot_ts = datetime.now(UTC)
    redis_client = get_redis_client()

    try:
        with lock_scope(
            redis_client=redis_client,
            source=source,
            account_id=account_id,
            ttl_seconds=lock_ttl_seconds,
            auto_renew=True,
        ):
            ch_client = get_ch_client()
            try:
                records = fetch_fn()
                rows = parse_fn(
                    records, run_id=run_id, account_id=account_id, snapshot_ts=snapshot_ts
                )
                if not rows:
                    observe_empty_payload(source)
                inserted = insert_rows(ch_client, table, columns, rows)
                log_task_run(
                    ch_client,
                    task_name,
                    run_id,
                    started_at,
                    "success",
                    inserted,
                    f"{source} snapshot",
                )
                return {"status": "success", "rows": inserted}
            except Exception as exc:
                log_task_run(ch_client, task_name, run_id, started_at, "failed", 0, str(exc))
                raise
    except LockNotAcquiredError:
        return {"status": "skipped", "reason": "lock_not_acquired"}

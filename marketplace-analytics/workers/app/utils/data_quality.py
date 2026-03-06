"""Data quality checks for scheduled warehouse validation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import clickhouse_connect

MAX_MART_STALENESS = timedelta(hours=2)
MAX_FUTURE_SKEW = timedelta(minutes=5)
MAX_SAMPLE_ROWS = 3


@dataclass(frozen=True)
class DataQualityIssue:
    check: str
    summary: str
    failures: int
    samples: list[dict[str, Any]]

    def as_meta(self) -> dict[str, Any]:
        return cast(dict[str, Any], _json_safe(asdict(self)))


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _query_dicts(
    client: clickhouse_connect.driver.Client,
    sql: str,
    parameters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    result = client.query(sql, parameters=parameters or {})
    return [dict(zip(result.column_names, row, strict=True)) for row in result.result_rows]


def _to_utc(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    return None


def evaluate_data_quality(
    client: clickhouse_connect.driver.Client,
) -> list[DataQualityIssue]:
    issues: list[DataQualityIssue] = []
    for check in (
        _check_stale_marts,
        _check_watermark_monotonicity,
        _check_duplicate_grains,
        _check_impossible_timestamps,
        _check_invalid_values,
    ):
        issue = check(client)
        if issue is not None:
            issues.append(issue)
    return issues


def _check_stale_marts(client: clickhouse_connect.driver.Client) -> DataQualityIssue | None:
    marts_have_run = bool(client.query("""
            SELECT count()
            FROM sys_task_runs
            WHERE task_name LIKE 'tasks.marts.%'
              AND status = 'success'
            """).result_rows[0][0])
    if not marts_have_run:
        return None

    cutoff = datetime.now(UTC) - MAX_MART_STALENESS
    samples: list[dict[str, Any]] = []

    for table_name in (
        "mrt_sales_daily",
        "mrt_stock_daily",
        "mrt_funnel_daily",
        "mrt_ads_daily",
    ):
        result = client.query(f"SELECT max(updated_at) AS last_updated FROM {table_name}")
        value = _to_utc(result.result_rows[0][0] if result.result_rows else None)
        if value is None or value < cutoff:
            samples.append(
                {
                    "table": table_name,
                    "last_updated": value.isoformat() if value is not None else None,
                    "cutoff": cutoff.isoformat(),
                }
            )

    if not samples:
        return None

    return DataQualityIssue(
        check="stale_marts",
        summary="mart tables are stale or empty after successful marts runs",
        failures=len(samples),
        samples=samples[:MAX_SAMPLE_ROWS],
    )


def _check_watermark_monotonicity(
    client: clickhouse_connect.driver.Client,
) -> DataQualityIssue | None:
    rows = _query_dicts(
        client,
        """
        SELECT source, account_id, watermark_ts, updated_at
        FROM sys_watermarks
        ORDER BY source, account_id, updated_at
        """,
    )
    previous: dict[tuple[str, str], datetime] = {}
    samples: list[dict[str, Any]] = []

    for row in rows:
        key = (str(row["source"]), str(row["account_id"]))
        current = _to_utc(row["watermark_ts"])
        if current is None:
            continue
        prior = previous.get(key)
        if prior is not None and current < prior:
            updated_at = _to_utc(row["updated_at"])
            samples.append(
                {
                    "source": key[0],
                    "account_id": key[1],
                    "previous_watermark": prior.isoformat(),
                    "watermark": current.isoformat(),
                    "updated_at": updated_at.isoformat() if updated_at is not None else None,
                }
            )
        previous[key] = current

    if not samples:
        return None

    return DataQualityIssue(
        check="watermark_monotonicity",
        summary="watermarks moved backwards for one or more source/account pairs",
        failures=len(samples),
        samples=samples[:MAX_SAMPLE_ROWS],
    )


def _check_duplicate_grains(client: clickhouse_connect.driver.Client) -> DataQualityIssue | None:
    duplicate_specs = (
        ("stg_sales", ("marketplace", "account_id", "order_id", "product_id", "event_ts")),
        ("stg_orders", ("marketplace", "account_id", "order_id", "event_ts")),
        ("stg_stocks", ("marketplace", "account_id", "day", "product_id", "warehouse_id")),
        ("stg_funnel_daily", ("marketplace", "account_id", "day", "product_id")),
        ("stg_ads_daily", ("marketplace", "account_id", "day", "campaign_id")),
        ("stg_finance_ops", ("marketplace", "account_id", "operation_id", "operation_ts")),
        ("mrt_sales_daily", ("marketplace", "account_id", "day", "product_id")),
        ("mrt_stock_daily", ("marketplace", "account_id", "day", "product_id", "warehouse_id")),
        ("mrt_funnel_daily", ("marketplace", "account_id", "day", "product_id")),
        ("mrt_ads_daily", ("marketplace", "account_id", "day", "campaign_id")),
    )
    samples: list[dict[str, Any]] = []
    failures = 0

    for table_name, columns in duplicate_specs:
        group_by = ", ".join(columns)
        rows = _query_dicts(
            client,
            f"""
            SELECT {group_by}, count() AS duplicate_count
            FROM {table_name}
            GROUP BY {group_by}
            HAVING duplicate_count > 1
            ORDER BY duplicate_count DESC
            LIMIT {MAX_SAMPLE_ROWS}
            """,
        )
        failures += len(rows)
        for row in rows:
            samples.append({"table": table_name, **row})

    if failures == 0:
        return None

    return DataQualityIssue(
        check="duplicate_grains",
        summary="canonical stg/mrt tables contain duplicate rows on expected grain",
        failures=failures,
        samples=samples[:MAX_SAMPLE_ROWS],
    )


def _check_impossible_timestamps(
    client: clickhouse_connect.driver.Client,
) -> DataQualityIssue | None:
    future_cutoff = datetime.now(UTC) + MAX_FUTURE_SKEW
    samples: list[dict[str, Any]] = []

    checks = (
        """
        SELECT 'raw_wb_sales' AS table_name, account_id, srid AS entity_id, event_ts AS bad_ts
        FROM raw_wb_sales
        WHERE event_ts > %(future_cutoff)s
        LIMIT %(limit)s
        """,
        """
        SELECT 'raw_wb_orders' AS table_name, account_id, srid AS entity_id, event_ts AS bad_ts
        FROM raw_wb_orders
        WHERE event_ts > %(future_cutoff)s
        LIMIT %(limit)s
        """,
        """
        SELECT
          'raw_ozon_postings' AS table_name,
          account_id,
          posting_number AS entity_id,
          created_at AS bad_ts
        FROM raw_ozon_postings
        WHERE created_at > %(future_cutoff)s
           OR (delivered_at IS NOT NULL AND delivered_at < created_at)
           OR (canceled_at IS NOT NULL AND canceled_at < created_at)
        LIMIT %(limit)s
        """,
        """
        SELECT
          'stg_sales' AS table_name,
          account_id,
          order_id AS entity_id,
          event_ts AS bad_ts
        FROM stg_sales
        WHERE event_ts > %(future_cutoff)s
        LIMIT %(limit)s
        """,
    )

    for sql in checks:
        samples.extend(
            _query_dicts(
                client,
                sql,
                parameters={
                    "future_cutoff": future_cutoff.replace(tzinfo=None),
                    "limit": MAX_SAMPLE_ROWS,
                },
            )
        )

    if not samples:
        return None

    return DataQualityIssue(
        check="impossible_timestamps",
        summary="future or chronologically impossible timestamps were detected",
        failures=len(samples),
        samples=samples[:MAX_SAMPLE_ROWS],
    )


def _check_invalid_values(client: clickhouse_connect.driver.Client) -> DataQualityIssue | None:
    samples: list[dict[str, Any]] = []

    checks = (
        """
        SELECT
          'mrt_stock_daily_negative' AS issue,
          marketplace,
          account_id,
          product_id,
          toString(stock_end) AS value
        FROM mrt_stock_daily
        WHERE stock_end < 0
        LIMIT %(limit)s
        """,
        """
        SELECT
          'mrt_ads_daily_negative_cost' AS issue,
          marketplace,
          account_id,
          campaign_id AS product_id,
          toString(cost) AS value
        FROM mrt_ads_daily
        WHERE cost < 0 OR revenue < 0
        LIMIT %(limit)s
        """,
        """
        SELECT
          'mrt_funnel_daily_impossible_counts' AS issue,
          marketplace,
          account_id,
          product_id,
          concat(toString(views), '/', toString(adds_to_cart), '/', toString(orders)) AS value
        FROM mrt_funnel_daily
        WHERE adds_to_cart > views OR orders > adds_to_cart
        LIMIT %(limit)s
        """,
    )

    for sql in checks:
        samples.extend(_query_dicts(client, sql, parameters={"limit": MAX_SAMPLE_ROWS}))

    if not samples:
        return None

    return DataQualityIssue(
        check="invalid_values",
        summary="negative or impossible aggregate values were detected",
        failures=len(samples),
        samples=samples[:MAX_SAMPLE_ROWS],
    )

"""Data freshness for the caller's organization: last mart rebuild, collector lag, errors."""

from __future__ import annotations

from typing import Any

from app.db.ch import query_dicts
from app.services.tenancy import account_scope_sql
from clickhouse_connect.driver import Client

FRESHNESS_MARTS = ("mrt_sales_daily", "mrt_stock_daily", "mrt_funnel_daily", "mrt_ads_daily")
COLLECTOR_TASK_PREFIXES = ("tasks.wb_collect.", "tasks.ozon_collect.")


class FreshnessService:
    def __init__(self, ch: Client, organization_id: str) -> None:
        self._ch = ch
        self._org = organization_id

    def summary(self) -> dict[str, Any]:
        marts = []
        for table in FRESHNESS_MARTS:
            rows = query_dicts(
                self._ch,
                "SELECT maxOrNull(day) AS last_day, maxOrNull(updated_at) AS updated_at"
                f" FROM {table}"
                f" WHERE {account_scope_sql('oid')}",
                {"oid": self._org},
            )
            row = rows[0] if rows else {}
            marts.append(
                {
                    "table": table,
                    "last_day": str(row.get("last_day") or "") or None,
                    "updated_at": row.get("updated_at"),
                }
            )

        # Watermark sources are named "<marketplace>_<dataset>" (e.g. wb_sales).
        watermarks = query_dicts(
            self._ch,
            "SELECT w.source AS source, w.account_id AS account_id,"
            " w.watermark_ts AS watermark_ts, w.updated_at AS updated_at,"
            " dateDiff('second', w.watermark_ts, now()) AS lag_seconds"
            " FROM sys_watermarks AS w FINAL"
            " WHERE (splitByChar('_', w.source)[1], w.account_id) IN ("
            "SELECT marketplace, account_id FROM dim_account FINAL"
            " WHERE organization_id = {oid:String})"
            " ORDER BY w.source, w.account_id",
            {"oid": self._org},
        )
        # Collector runs are shared infrastructure: expose only counts, no messages.
        failures = query_dicts(
            self._ch,
            "SELECT task_name, count() AS failures, max(finished_at) AS last_failure"
            " FROM sys_task_runs"
            " WHERE status = 'failed' AND finished_at >= now() - INTERVAL 24 HOUR"
            " AND (startsWith(task_name, {p1:String}) OR startsWith(task_name, {p2:String}))"
            " GROUP BY task_name ORDER BY failures DESC",
            {"p1": COLLECTOR_TASK_PREFIXES[0], "p2": COLLECTOR_TASK_PREFIXES[1]},
        )
        return {"marts": marts, "collectors": watermarks, "source_errors_24h": failures}

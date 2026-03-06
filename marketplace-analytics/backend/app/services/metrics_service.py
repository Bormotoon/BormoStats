"""Service layer for analytics metrics."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import clickhouse_connect
from app.db.ch import query_dicts

_QUERIES_DIR = Path(__file__).resolve().parents[1] / "db" / "queries"


def _load_sql(name: str) -> str:
    return (_QUERIES_DIR / name).read_text(encoding="utf-8")


class MetricsService:
    def __init__(self, client: clickhouse_connect.driver.Client) -> None:
        self.client = client

    def sales_daily(
        self,
        date_from: date,
        date_to: date,
        marketplace: str,
        account_id: str,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        return query_dicts(
            self.client,
            _load_sql("sales.sql"),
            {
                "date_from": date_from,
                "date_to": date_to,
                "marketplace": marketplace,
                "account_id": account_id,
                "limit": limit,
                "offset": offset,
            },
        )

    def stocks_current(
        self,
        marketplace: str,
        account_id: str,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        return query_dicts(
            self.client,
            _load_sql("stocks.sql"),
            {
                "marketplace": marketplace,
                "account_id": account_id,
                "limit": limit,
                "offset": offset,
            },
        )

    def funnel_daily(
        self,
        date_from: date,
        date_to: date,
        marketplace: str,
        account_id: str,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        return query_dicts(
            self.client,
            _load_sql("funnel.sql"),
            {
                "date_from": date_from,
                "date_to": date_to,
                "marketplace": marketplace,
                "account_id": account_id,
                "limit": limit,
                "offset": offset,
            },
        )

    def ads_daily(
        self,
        date_from: date,
        date_to: date,
        marketplace: str,
        account_id: str,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        return query_dicts(
            self.client,
            _load_sql("ads.sql"),
            {
                "date_from": date_from,
                "date_to": date_to,
                "marketplace": marketplace,
                "account_id": account_id,
                "limit": limit,
                "offset": offset,
            },
        )

    def kpis(
        self,
        marketplace: str,
        account_id: str,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        return query_dicts(
            self.client,
            _load_sql("kpis.sql"),
            {
                "marketplace": marketplace,
                "account_id": account_id,
                "limit": limit,
                "offset": offset,
            },
        )

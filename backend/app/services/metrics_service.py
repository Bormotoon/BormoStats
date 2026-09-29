"""Service layer for analytics metrics.

Every query is scoped to one organization: rows are limited to the accounts that
``dim_account`` assigns to ``organization_id`` (see ``app.services.tenancy``).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import clickhouse_connect
from app.db.ch import query_dicts
from app.services.sql_loader import load_sql

_QUERIES_DIR = Path(__file__).resolve().parents[1] / "db" / "queries"


def _load_sql(name: str) -> str:
    return load_sql(_QUERIES_DIR, name)


class MetricsService:
    def __init__(self, client: clickhouse_connect.driver.Client) -> None:
        self.client = client

    def _run(self, query_name: str, **parameters: Any) -> list[dict[str, Any]]:
        return query_dicts(self.client, _load_sql(query_name), parameters)

    def sales_daily(
        self,
        *,
        organization_id: str,
        date_from: date,
        date_to: date,
        marketplace: str,
        account_id: str,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        return self._run(
            "sales.sql",
            organization_id=organization_id,
            date_from=date_from,
            date_to=date_to,
            marketplace=marketplace,
            account_id=account_id,
            limit=limit,
            offset=offset,
        )

    def stocks_current(
        self,
        *,
        organization_id: str,
        marketplace: str,
        account_id: str,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        return self._run(
            "stocks.sql",
            organization_id=organization_id,
            marketplace=marketplace,
            account_id=account_id,
            limit=limit,
            offset=offset,
        )

    def funnel_daily(
        self,
        *,
        organization_id: str,
        date_from: date,
        date_to: date,
        marketplace: str,
        account_id: str,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        return self._run(
            "funnel.sql",
            organization_id=organization_id,
            date_from=date_from,
            date_to=date_to,
            marketplace=marketplace,
            account_id=account_id,
            limit=limit,
            offset=offset,
        )

    def ads_daily(
        self,
        *,
        organization_id: str,
        date_from: date,
        date_to: date,
        marketplace: str,
        account_id: str,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        return self._run(
            "ads.sql",
            organization_id=organization_id,
            date_from=date_from,
            date_to=date_to,
            marketplace=marketplace,
            account_id=account_id,
            limit=limit,
            offset=offset,
        )

    def kpis(
        self,
        *,
        organization_id: str,
        marketplace: str,
        account_id: str,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        return self._run(
            "kpis.sql",
            organization_id=organization_id,
            marketplace=marketplace,
            account_id=account_id,
            limit=limit,
            offset=offset,
        )

from __future__ import annotations

from typing import Any

from app.db.ch import PARTITION_LOCAL_FINAL
from app.services.tenancy import account_scope_sql
from clickhouse_connect.driver import Client

_ABC_XYZ_COLS = (
    "day, marketplace, account_id, product_id, revenue_60d, share_pct, cumulative_share_pct,"
    " abc_class, daily_mean_qty, daily_stddev_qty, cv_pct, xyz_class"
)


class AbcXyzService:
    def __init__(self, ch: Client, organization_id: str) -> None:
        self._ch = ch
        self._org = organization_id

    def get_analysis(
        self, marketplace: str | None = None, account_id: str | None = None
    ) -> list[dict[str, Any]]:
        where = [account_scope_sql("oid")]
        params: dict[str, object] = {"oid": self._org}
        if marketplace:
            where.append("marketplace = {mp:String}")
            params["mp"] = marketplace
        if account_id:
            where.append("account_id = {aid:String}")
            params["aid"] = account_id
        rows = self._ch.query(
            f"SELECT {_ABC_XYZ_COLS} FROM mrt_abc_xyz_analysis FINAL"
            f" WHERE {' AND '.join(where)} ORDER BY revenue_60d DESC LIMIT 5000",
            parameters=params,
            settings=PARTITION_LOCAL_FINAL,
        )
        return [
            {
                "day": str(r[0]),
                "marketplace": r[1],
                "account_id": r[2],
                "product_id": r[3],
                "revenue_60d": float(r[4]),
                "share_pct": float(r[5]),
                "cumulative_share_pct": float(r[6]),
                "abc_class": r[7],
                "daily_mean_qty": float(r[8]),
                "daily_stddev_qty": float(r[9]),
                "cv_pct": float(r[10]),
                "xyz_class": r[11],
            }
            for r in rows.result_rows
        ]

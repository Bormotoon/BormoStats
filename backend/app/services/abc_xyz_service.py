from __future__ import annotations

from typing import Any

from app.db.ch import PARTITION_LOCAL_FINAL
from app.services.tenancy import account_scope_sql
from clickhouse_connect.driver import Client

_ABC_XYZ_COLS = (
    "a.day, a.marketplace, a.account_id, a.product_id, a.revenue_60d, a.share_pct,"
    " a.cumulative_share_pct, a.abc_class, a.daily_mean_qty, a.daily_stddev_qty, a.cv_pct,"
    " a.xyz_class, card.offer_id, card.title, card.image_url"
)
# the supplier article, name and photo of a product from its current card (WB nmID, Ozon SKU)
_CARDS = (
    "SELECT marketplace, account_id, product_id, any(offer_id) AS offer_id,"
    " anyIf(title, title != '') AS title, anyIf(image_url, image_url != '') AS image_url"
    " FROM mrt_price_current FINAL GROUP BY marketplace, account_id, product_id"
)


class AbcXyzService:
    def __init__(self, ch: Client, organization_id: str) -> None:
        self._ch = ch
        self._org = organization_id

    def get_analysis(
        self, marketplace: str | None = None, account_id: str | None = None
    ) -> list[dict[str, Any]]:
        params: dict[str, object] = {"oid": self._org}
        filters = []
        if marketplace:
            filters.append("marketplace = {mp:String}")
            params["mp"] = marketplace
        if account_id:
            filters.append("account_id = {aid:String}")
            params["aid"] = account_id
        scope = " AND ".join([account_scope_sql("oid"), *filters])
        scope_a = " AND ".join([account_scope_sql("oid", alias="a"), *(f"a.{f}" for f in filters)])
        # the mart keeps one snapshot per day as class history; the page shows the latest
        rows = self._ch.query(
            f"SELECT {_ABC_XYZ_COLS} FROM mrt_abc_xyz_analysis AS a FINAL"
            f" LEFT JOIN ({_CARDS}) AS card ON card.marketplace = a.marketplace"
            " AND card.account_id = a.account_id AND card.product_id = a.product_id"
            f" WHERE {scope_a}"
            f" AND a.day = (SELECT max(day) FROM mrt_abc_xyz_analysis WHERE {scope})"
            " ORDER BY a.revenue_60d DESC LIMIT 5000",
            parameters=params,
            settings={**PARTITION_LOCAL_FINAL, "join_use_nulls": 1},
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
                "offer_id": r[12] or None,
                "title": r[13] or None,
                "image_url": r[14] or None,
            }
            for r in rows.result_rows
        ]

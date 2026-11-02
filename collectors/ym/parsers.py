"""Pure parsers for Yandex Market Partner API payloads and reports."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from typing import Any

from collectors.common.time import as_ch_datetime, parse_dt


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if isinstance(value, str):
            value = value.replace("\xa0", "").replace(" ", "").replace(",", ".")
        return float(value)
    except TypeError, ValueError:
        return default


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except TypeError, ValueError:
        return default


def _dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    if isinstance(value, str):
        try:
            parsed = parse_dt(value)
            return parsed if parsed is not None else datetime.now(UTC)
        except ValueError:
            pass
    return datetime.now(UTC)


def _product_id(item: dict[str, Any]) -> int:
    sku = _int(item.get("marketSku") or item.get("market_sku") or item.get("sku"))
    if sku > 0:
        return sku
    offer_id = str(item.get("offerId") or item.get("offer_id") or "")
    from clickhouse_cityhash.cityhash import CityHash64  # type: ignore[import-untyped]

    return int(CityHash64(offer_id))


def _rows(records: list[dict[str, Any]], run_id: str, account_id: str) -> list[dict[str, Any]]:
    return [
        {
            "run_id": run_id,
            "account_id": account_id,
            "offer_id": str(row.get("offerId") or row.get("offer_id") or ""),
            "product_id": _product_id(row),
            "payload": json.dumps(row, ensure_ascii=True, default=str),
        }
        for row in records
    ]


def parse_orders(
    records: list[dict[str, Any]], run_id: str, account_id: str
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for order in records:
        order_id = _int(order.get("id") or order.get("orderId"))
        created = _dt(order.get("creationDate") or order.get("createdAt"))
        updated = _dt(
            order.get("statusUpdateDate")
            or order.get("updateDate")
            or order.get("updatedAt")
            or created
        )
        order_items: Any = order.get("items")
        if not isinstance(order_items, list):
            continue
        for item in order_items:
            item = _dict(item)
            prices: Any = item.get("prices")
            if not isinstance(prices, list):
                prices = []
            buyer = seller = subsidy = 0.0
            for price in prices:
                price = _dict(price)
                value = _float(price.get("costPerItem") or price.get("value"))
                kind = str(price.get("type") or "").upper()
                if kind == "BUYER":
                    buyer = value
                elif kind in {"SUBSIDY", "CASHBACK", "MARKETPLACE"}:
                    subsidy += value
                else:
                    seller = value
            if isinstance(item.get("prices"), dict):
                components = item["prices"]
                count = max(1, _int(item.get("count")))
                buyer = _float(_dict(components.get("payment")).get("value")) / count
                cashback = _float(_dict(components.get("cashback")).get("value")) / count
                subsidy = _float(_dict(components.get("subsidy")).get("value")) / count
                seller = buyer + cashback + subsidy
            elif not seller:
                seller = buyer + subsidy
            offer_id = str(item.get("offerId") or item.get("shopSku") or "")
            result.append(
                {
                    "run_id": run_id,
                    "account_id": account_id,
                    "order_id": order_id,
                    "offer_id": offer_id,
                    "product_id": _product_id(item),
                    "status": str(order.get("status") or "UNKNOWN"),
                    "substatus": str(order.get("substatus") or ""),
                    "created_at": as_ch_datetime(created),
                    "updated_at": as_ch_datetime(updated),
                    "qty": max(0, _int(item.get("count"))),
                    "buyer_price": buyer,
                    "seller_price": seller,
                    "subsidy": subsidy,
                    "payload": json.dumps(
                        {"order": order, "item": item}, ensure_ascii=True, default=str
                    ),
                    "ingested_at": as_ch_datetime(datetime.now(UTC)),
                }
            )
    return result


def parse_stats_orders(
    records: list[dict[str, Any]], run_id: str, account_id: str
) -> list[dict[str, Any]]:
    return parse_orders(records, run_id, account_id)


def parse_stocks(
    records: list[dict[str, Any]],
    run_id: str,
    account_id: str,
    snapshot_ts: datetime,
) -> list[dict[str, Any]]:
    result = []
    for record in records:
        if isinstance(record.get("offers"), list):
            for offer in record["offers"]:
                counts = {s.get("type"): s.get("count", 0) for s in offer.get("stocks", [])}
                result.extend(
                    parse_stocks(
                        [
                            {
                                **offer,
                                "stocks": [
                                    {
                                        "warehouseId": record.get("warehouseId"),
                                        "warehouseName": record.get("warehouseName", ""),
                                        "fit": counts.get("FIT", 0),
                                        "freeze": counts.get("FREEZE", 0),
                                    }
                                ],
                            }
                        ],
                        run_id,
                        account_id,
                        snapshot_ts,
                    )
                )
            continue
        for stock in (
            record.get("stocks", []) if isinstance(record.get("stocks"), list) else [record]
        ):
            stock = _dict(stock)
            warehouse = _dict(stock.get("warehouse"))
            result.append(
                {
                    "run_id": run_id,
                    "account_id": account_id,
                    "offer_id": str(record.get("offerId") or stock.get("offerId") or ""),
                    "product_id": _product_id(record),
                    "warehouse_id": _int(warehouse.get("id") or stock.get("warehouseId")),
                    "warehouse_name": str(
                        warehouse.get("name") or stock.get("warehouseName") or ""
                    ),
                    "stock_fit": _int(stock.get("fit") or stock.get("count")),
                    "stock_freeze": _int(stock.get("freeze")),
                    "snapshot_ts": as_ch_datetime(snapshot_ts),
                    "payload": json.dumps(
                        {"offer": record, "stock": stock}, ensure_ascii=True, default=str
                    ),
                }
            )
    return result


def parse_offer_mappings(
    records: list[dict[str, Any]], run_id: str, account_id: str
) -> list[dict[str, Any]]:
    result = []
    for record in records:
        mapping = _dict(record.get("mapping")) or record
        offer = _dict(record.get("offer")) or _dict(mapping.get("offer"))
        market = _dict(mapping.get("market")) or mapping
        result.append(
            {
                "run_id": run_id,
                "account_id": account_id,
                "offer_id": str(offer.get("offerId") or record.get("offerId") or ""),
                "product_id": _product_id(
                    offer | {"marketSku": market.get("marketSku") or market.get("id")}
                ),
                "market_sku": _int(market.get("id") or market.get("marketSku")),
                "name": str(
                    market.get("marketSkuName") or market.get("name") or offer.get("name") or ""
                ),
                "purchase_price": _float(_dict(offer.get("purchasePrice")).get("value")),
                "pictures": offer.get("pictures") or market.get("pictures", []),
                "ingested_at": as_ch_datetime(datetime.now(UTC)),
                "payload": json.dumps(record, ensure_ascii=True, default=str),
            }
        )
    return result


def parse_prices(
    records: list[dict[str, Any]], run_id: str, account_id: str, snapshot_ts: datetime
) -> list[dict[str, Any]]:
    result = []
    for record in records:
        price = _dict(record.get("price"))
        buyer = record.get("buyerPrice") or record.get("cofinancePrice")
        result.append(
            {
                "run_id": run_id,
                "account_id": account_id,
                "offer_id": str(record.get("offerId") or ""),
                "product_id": _product_id(record),
                "list_price": _float(price.get("discountBase")),
                "seller_price": _float(price.get("value")),
                "purchase_price": _float(_dict(record.get("purchasePrice")).get("value")),
                "cofinance_price": _float(record.get("cofinancePrice"))
                if record.get("cofinancePrice") is not None
                else None,
                "buyer_price": _float(buyer) if buyer is not None else None,
                "commission_pct": _float(record.get("commissionPct")),
                "logistics_rub": _float(record.get("logisticsRub")),
                "acquiring_rub": _float(record.get("acquiringRub")),
                "snapshot_ts": as_ch_datetime(snapshot_ts),
                "payload": json.dumps(record, ensure_ascii=True, default=str),
            }
        )
    return result


def normalize_report_row(record: dict[str, Any]) -> dict[str, Any]:
    """CSV uses UPPER_SNAKE_CASE, JSON uses camelCase (official report contract)."""
    result = {}
    for key, value in record.items():
        parts = key.lower().split("_")
        normalized = (
            parts[0] + "".join(part.title() for part in parts[1:]) if key.isupper() else key
        )
        result[normalized] = value
    if "shopSku" in result:
        result.setdefault("offerId", result["shopSku"])
    return result


def _report_rows(
    records: list[dict[str, Any]], run_id: str, account_id: str, kind: str
) -> list[dict[str, Any]]:
    result = []
    for record in records:
        record = normalize_report_row(record)
        day_value = (
            record.get("transactionDate")
            or record.get("date")
            or record.get("eventDate")
            or record.get("day")
        )
        try:
            day = date.fromisoformat(str(day_value)[:10])
        except ValueError:
            try:
                day = datetime.strptime(str(day_value)[:10], "%d.%m.%Y").date()
            except ValueError:
                raise ValueError(f"Yandex report row has invalid date: {day_value!r}") from None
        result.append(
            {
                **_rows([record], run_id, account_id)[0],
                "kind": kind,
                "_campaignId": record.get("saleCampaignId") or record.get("_campaignId", ""),
                "transaction_type": record.get("transactionType", ""),
                "service_type": " ".join(
                    str(v)
                    for v in (
                        record.get("transactionSource"),
                        record.get("serviceType") or record.get("offerOrServiceName"),
                    )
                    if v
                ),
                "order_id": _int(record.get("orderId")) or None,
                "payout": _float(record.get("payout")),
                "day": day,
                "shows": _int(record.get("shows") or record.get("impressions")),
                "clicks": _int(record.get("clicks")),
                "to_cart": _int(record.get("toCart") or record.get("cart")),
                "orders": _int(
                    record.get("orders") or record.get("orderItems") or record.get("orderedCount")
                ),
                "revenue": _float(
                    record.get("revenue")
                    or record.get("orderItemsTotalAmount")
                    or record.get("orderedAmount")
                ),
                "amount": _float(
                    record.get("amount")
                    or record.get("transactionSum")
                    or record.get("realCost")
                    or record.get("cost")
                    or record.get("sum")
                ),
                "transaction_id": str(
                    record.get("transactionId")
                    or record.get("id")
                    or hashlib.sha256(
                        json.dumps(record, sort_keys=True, default=str).encode()
                    ).hexdigest()
                ),
                "payload": json.dumps(record, ensure_ascii=True, default=str),
                "ingested_at": as_ch_datetime(datetime.now(UTC)),
            }
        )
    return result


def parse_united_netting(
    records: list[dict[str, Any]], run_id: str, account_id: str
) -> list[dict[str, Any]]:
    return _report_rows(records, run_id, account_id, "finance")


def parse_shows_sales(
    records: list[dict[str, Any]], run_id: str, account_id: str
) -> list[dict[str, Any]]:
    return _report_rows(records, run_id, account_id, "funnel")


def parse_shows_boost(
    records: list[dict[str, Any]], run_id: str, account_id: str
) -> list[dict[str, Any]]:
    return _report_rows(records, run_id, account_id, "ads")


def parse_feedbacks(
    records: list[dict[str, Any]], run_id: str, account_id: str
) -> list[dict[str, Any]]:
    result = []
    for record in records:
        description = _dict(record.get("description"))
        statistics = _dict(record.get("statistics"))
        result.append(
            {
                "run_id": run_id,
                "account_id": account_id,
                "review_id": str(record.get("feedbackId") or ""),
                "offer_id": str(
                    _dict(record.get("identifiers")).get("offerId") or record.get("offerId") or ""
                ),
                "product_id": _product_id(record | _dict(record.get("identifiers"))),
                "rating": _int(statistics.get("rating")),
                "text": str(description.get("comment") or ""),
                "pros": str(description.get("advantages") or ""),
                "cons": str(description.get("disadvantages") or ""),
                "is_answered": not bool(record.get("needReaction", False)),
                "created_at": as_ch_datetime(_dt(record.get("createdAt"))),
                "payload": json.dumps(record, ensure_ascii=True, default=str),
            }
        )
    return result

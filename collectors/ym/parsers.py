"""Pure parsers for Yandex Market Partner API payloads and reports."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

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


def _stats_dt(value: Any) -> datetime:
    # Statistics API documents timestamps without an offset in Moscow time.
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=ZoneInfo("Europe/Moscow")).astimezone(UTC)
        except ValueError:
            pass
    return _dt(value)


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
                        record.get("serviceType"),
                    )
                    if v
                ),
                "product_name": record.get("offerOrServiceName") or record.get("productName"),
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


def parse_order_statistics(
    records: list[dict[str, Any]], run_id: str, account_id: str
) -> list[dict[str, Any]]:
    """Keep per-order prices; attribute order-level fees only to single-offer orders."""
    rows: list[dict[str, Any]] = []

    def attributed(fees: dict[str, float], count: int, types: set[str]) -> float | None:
        values = [value for key, value in fees.items() if key in types]
        return sum(values) if count == 1 and values else None

    for order in records:
        items = [
            item
            for item in order.get("items", [])
            if isinstance(item, dict) and item.get("shopSku") and not item.get("shopServiceType")
        ]
        present = {str(item["shopSku"]) for item in items}
        items.extend(
            item
            for item in order.get("initialItems", [])
            if isinstance(item, dict)
            and item.get("shopSku")
            and not item.get("shopServiceType")
            and str(item["shopSku"]) not in present
        )
        item_count = len(items)
        commissions = [c for c in order.get("commissions", []) if isinstance(c, dict)]
        fees: dict[str, float] = {}
        for commission in commissions:
            kind = str(commission.get("type") or "")
            if "actual" in commission:
                fees[kind] = fees.get(kind, 0) + _float(commission["actual"])
        for item in items:
            price_parts = {
                str(p.get("type")): _float(p.get("costPerItem"))
                for p in item.get("prices", [])
                if isinstance(p, dict) and p.get("costPerItem") is not None
            }

            rows.append(
                {
                    "run_id": run_id,
                    "account_id": account_id,
                    "order_id": _int(order.get("id")),
                    "offer_id": str(item["shopSku"]),
                    "product_id": _product_id(item | {"offerId": item["shopSku"]}),
                    "status": str(order.get("status") or "UNKNOWN"),
                    "created_at": as_ch_datetime(_stats_dt(order.get("creationDate"))),
                    "updated_at": as_ch_datetime(
                        _stats_dt(order.get("statusUpdateDate") or order.get("creationDate"))
                    ),
                    "qty": max(0, _int(item.get("count"))),
                    "buyer_price": price_parts.get("BUYER"),
                    "cashback": price_parts.get("CASHBACK"),
                    "marketplace_discount": price_parts.get("MARKETPLACE"),
                    "cofinance_value": _float(item["cofinanceValue"])
                    if item.get("cofinanceValue") is not None
                    else None,
                    "fee": attributed(fees, item_count, {"FEE"}),
                    "acquiring": attributed(fees, item_count, {"AGENCY", "PAYMENT_TRANSFER"}),
                    "logistics": attributed(
                        fees,
                        item_count,
                        {
                            "DELIVERY_TO_CUSTOMER",
                            "EXPRESS_DELIVERY_TO_CUSTOMER",
                            "SORTING",
                            "INTAKE_SORTING",
                            "CROSSREGIONAL_DELIVERY",
                            "AGENCY_COMMISSION_3PL",
                        },
                    ),
                    "payload": json.dumps(
                        {
                            "item": item,
                            "initialItems": order.get("initialItems", []),
                            "commissions": commissions,
                        },
                        ensure_ascii=True,
                        default=str,
                    ),
                    "ingested_at": as_ch_datetime(datetime.now(UTC)),
                }
            )
    return rows


def parse_tariff_quotes(
    records: list[dict[str, Any]], run_id: str, account_id: str
) -> list[dict[str, Any]]:
    """Preserve ambiguous alternatives without pretending they are additive."""
    rows = []
    groups = {
        "fee": {"FEE"},
        "acquiring": {"AGENCY_COMMISSION", "PAYMENT_TRANSFER"},
        "logistics": {
            "DELIVERY_TO_CUSTOMER",
            "EXPRESS_DELIVERY",
            "SORTING",
            "MIDDLE_MILE",
            "CROSSREGIONAL_DELIVERY",
            "ITEM_BOOKING",
        },
    }
    for record in records:
        tariffs = record.get("tariffs") or []
        values: dict[str, float | None] = {}
        for name, kinds in groups.items():
            matches = [t for t in tariffs if isinstance(t, dict) and t.get("type") in kinds]
            counts = [str(t.get("type")) for t in matches]
            values[name] = (
                sum(_float(t["amount"]) for t in matches)
                if matches
                and len(counts) == len(set(counts))
                and all(t.get("amount") is not None for t in matches)
                else None
            )
        rows.append(
            {
                "run_id": run_id,
                "account_id": account_id,
                "offer_id": str(record["_offerId"]),
                "price": _float(record["_price"]),
                **values,
                "payload": json.dumps(record, ensure_ascii=True, default=str),
                "snapshot_ts": as_ch_datetime(datetime.now(UTC)),
            }
        )
    return rows

"""Price breakdown, price comparison, desired prices and cost prices for one organization."""

from __future__ import annotations

import re
import uuid
from typing import Any

from app.db.ch import query_dicts, utc_now
from app.models.pricing import (
    OfferCost,
    OfferCostImportResult,
    PriceBreakdownRow,
    PriceCompareRow,
    TargetPriceImportResult,
    TargetPriceSet,
    WbDocumentsCard,
    WbDocumentsCheck,
)
from app.models.repricer import PriceRule, PriceRuleCreate, PriceRuleUpdate, default_fallback
from app.services.repricer_service import RepricerService
from app.services.tenancy import account_scope_sql, ensure_account_access
from clickhouse_connect.driver import Client

_PRICE_COLS = (
    "p.marketplace AS marketplace, p.account_id AS account_id, p.offer_id AS offer_id,"
    " p.product_id AS product_id, p.title AS title, p.image_url AS image_url,"
    " p.list_price AS list_price, p.seller_discount_pct AS seller_discount_pct,"
    " p.seller_price AS seller_price, p.mp_discount_pct AS mp_discount_pct,"
    " p.mp_discount_scope AS mp_discount_scope, p.mp_discount_samples AS mp_discount_samples,"
    " p.buyer_price AS buyer_price, p.commission_pct AS commission_pct,"
    " p.commission_rub AS commission_rub, p.acquiring_rub AS acquiring_rub,"
    " p.logistics_rub AS logistics_rub, p.fees_rub AS fees_rub, p.cost_price AS cost_price,"
    " p.margin_rub AS margin_rub, p.margin_pct AS margin_pct,"
    " p.breakeven_price AS breakeven_price, p.min_price AS min_price,"
    " p.auto_actions_enabled AS auto_actions_enabled, p.price_index_color AS price_index_color,"
    " p.price_seen_at AS price_seen_at"
)
# the latest rule per card; a card may carry an older rule created through /repricer/rules
_RULES = (
    "SELECT marketplace, account_id, product_id,"
    " argMax(rule_id, updated_at) AS rule_id, argMax(mode, updated_at) AS mode,"
    " argMax(target_price, updated_at) AS target_price,"
    " argMax(no_discount_fallback, updated_at) AS no_discount_fallback,"
    " argMax(is_active, updated_at) AS is_active, argMax(dry_run, updated_at) AS dry_run"
    " FROM dim_price_rule FINAL GROUP BY marketplace, account_id, product_id"
)
_SEPARATORS = (";", "\t", ",")
_MAX_IMPORT_ERRORS = 50
# the latest version of every rule of one marketplace; a card may have several rules
_LATEST_RULES = (
    "SELECT r.rule_id AS rule_id, r.marketplace AS marketplace, r.account_id AS account_id,"
    " r.product_id AS product_id, r.mode AS mode, r.target_price AS target_price,"
    " r.max_step_pct AS max_step_pct, r.no_discount_fallback AS no_discount_fallback,"
    " r.min_price AS min_price, r.max_price AS max_price,"
    " r.target_margin_percent AS target_margin_percent, r.is_active AS is_active,"
    " r.dry_run AS dry_run, r.created_at AS created_at, r.updated_at AS updated_at"
    " FROM dim_price_rule AS r FINAL"
)


class PricingService:
    def __init__(self, ch: Client, organization_id: str) -> None:
        self._ch = ch
        self._org = organization_id

    def _scope(
        self, alias: str, marketplace: str | None, account_id: str | None
    ) -> tuple[str, dict[str, object]]:
        where = [account_scope_sql("oid", alias=alias)]
        params: dict[str, object] = {"oid": self._org}
        if marketplace:
            where.append(f"{alias}.marketplace = {{mp:String}}")
            params["mp"] = marketplace
        if account_id:
            where.append(f"{alias}.account_id = {{aid:String}}")
            params["aid"] = account_id
        return " WHERE " + " AND ".join(where), params

    def breakdown(
        self, marketplace: str | None = None, account_id: str | None = None
    ) -> list[PriceBreakdownRow]:
        clause, params = self._scope("p", marketplace, account_id)
        rows = query_dicts(
            self._ch,
            f"SELECT {_PRICE_COLS}, r.rule_id AS rule_id, r.mode AS mode,"
            " r.target_price AS target_price, r.no_discount_fallback AS no_discount_fallback,"
            " r.is_active AS rule_is_active,"
            " r.dry_run AS rule_dry_run"
            " FROM mrt_price_current AS p FINAL"
            f" LEFT JOIN ({_RULES}) AS r"
            " ON r.marketplace = p.marketplace AND r.account_id = p.account_id"
            " AND r.product_id = p.offer_id"
            f"{clause}"
            " ORDER BY p.offer_id, p.marketplace LIMIT 20000",
            params,
            settings={"join_use_nulls": 1},
        )
        return [_breakdown_row(r) for r in rows]

    def compare(self, account_id: str | None = None) -> list[PriceCompareRow]:
        clause, params = self._scope("p", None, account_id)
        rows = query_dicts(
            self._ch,
            "SELECT p.offer_id AS offer_id, anyIf(p.title, p.title IS NOT NULL) AS title,"
            " anyIf(p.image_url, p.image_url IS NOT NULL) AS image_url,"
            " anyIf(p.seller_price, p.marketplace = 'wb') AS wb_seller_price,"
            " anyIf(p.buyer_price, p.marketplace = 'wb') AS wb_buyer_price,"
            " anyIf(p.seller_price, p.marketplace = 'ozon') AS ozon_seller_price,"
            " anyIf(p.buyer_price, p.marketplace = 'ozon') AS ozon_buyer_price,"
            " countIf(p.marketplace = 'wb') AS on_wb, countIf(p.marketplace = 'ozon') AS on_ozon"
            " FROM mrt_price_current AS p FINAL"
            f"{clause}"
            " GROUP BY p.offer_id ORDER BY p.offer_id LIMIT 20000",
            params,
        )
        return [_compare_row(r) for r in rows]

    def wb_documents(self) -> WbDocumentsCheck:
        """WB cards whose "documents are not required" tick is off in the latest snapshot.

        Without it WB marks the card "Документы не загружены" and may block it. The tick is
        ``card.documents.excludeDocuments`` of content/v2/get/cards/list; the repricer only
        writes prices and never touches it.
        """
        clause, params = self._scope("r", "wb", None)
        rows = query_dicts(
            self._ch,
            "SELECT r.account_id AS account_id,"
            " JSONExtractString(o.body, 'card', 'vendorCode') AS offer_id,"
            " toString(JSONExtractUInt(o.body, 'card', 'nmID')) AS product_id,"
            " JSONExtractString(o.body, 'card', 'title') AS title,"
            " JSONExtractInt(o.body, 'card', 'documents', 'overallVerdict', 'status')"
            " AS verdict_status,"
            " JSONExtractString(o.body, 'card', 'documents', 'overallVerdict', 'reason')"
            " AS verdict_reason"
            " FROM hist_refs AS r FINAL"
            " INNER JOIN hist_objects AS o FINAL ON o.object_hash = r.head_object"
            f"{clause} AND r.repo = 'product' AND r.is_deleted = 0"
            " AND NOT JSONExtractBool(o.body, 'card', 'documents', 'excludeDocuments')"
            " ORDER BY offer_id",
            params,
        )
        images = self._card_images("wb", [r["product_id"] for r in rows])
        seen = self._ch.query(
            "SELECT max(finished_at) FROM sys_task_runs"
            " WHERE task_name = 'tasks.history.wb_catalog_snapshot' AND status = 'success'"
        ).result_rows
        checked_at = seen[0][0] if seen and seen[0][0] and seen[0][0].year > 1970 else None
        return WbDocumentsCheck(
            checked_at=str(checked_at) if checked_at else None,
            cards=[
                WbDocumentsCard(
                    account_id=r["account_id"],
                    offer_id=r["offer_id"],
                    product_id=r["product_id"],
                    title=r["title"] or None,
                    image_url=images.get((r["account_id"], r["product_id"])),
                    verdict_status=int(r["verdict_status"]),
                    verdict_reason=r["verdict_reason"],
                )
                for r in rows
            ],
        )

    def _card_images(self, marketplace: str, products: list[str]) -> dict[tuple[str, str], str]:
        if not products:
            return {}
        clause, params = self._scope("p", marketplace, None)
        rows = query_dicts(
            self._ch,
            "SELECT p.account_id AS account_id, p.product_id AS product_id,"
            " any(p.image_url) AS image_url"
            f" FROM mrt_price_current AS p FINAL{clause}"
            " AND p.product_id IN {products:Array(String)} AND p.image_url != ''"
            " GROUP BY p.account_id, p.product_id",
            {**params, "products": products},
        )
        return {(r["account_id"], r["product_id"]): r["image_url"] for r in rows}

    def set_target(self, marketplace: str, offer_id: str, data: TargetPriceSet) -> PriceRule:
        """Create the card's price rule (dry-run) or update the latest one."""
        ensure_account_access(self._ch, self._org, marketplace, data.account_id)
        repricer = RepricerService(self._ch, self._org)
        existing = self._latest_rule_id(marketplace, data.account_id, offer_id)
        if existing is not None:
            rule = repricer.update_rule(
                existing,
                PriceRuleUpdate(
                    mode=data.mode,
                    target_price=data.target_price,
                    min_price=data.min_price,
                    max_price=data.max_price,
                    max_step_pct=data.max_step_pct,
                    no_discount_fallback=data.no_discount_fallback,
                ),
            )
            if rule is not None:
                return rule
        return repricer.create_rule(
            PriceRuleCreate(
                marketplace=marketplace,
                account_id=data.account_id,
                product_id=offer_id,
                mode=data.mode,
                target_price=data.target_price,
                min_price=data.min_price or 0,
                max_price=data.max_price or 0,
                max_step_pct=data.max_step_pct or 10,
                no_discount_fallback=data.no_discount_fallback,
                dry_run=True,
            )
        )

    def _latest_rule_id(self, marketplace: str, account_id: str, offer_id: str) -> str | None:
        clause, params = self._scope("r", marketplace, account_id)
        rows = self._ch.query(
            f"SELECT r.rule_id FROM dim_price_rule AS r FINAL{clause}"
            " AND r.product_id = {offer:String} ORDER BY r.updated_at DESC LIMIT 1",
            parameters={**params, "offer": offer_id},
        ).result_rows
        return str(rows[0][0]) if rows else None

    def _latest_rules(self, marketplace: str) -> dict[tuple[str, str], PriceRule]:
        """The newest rule of each card (account, article) of the marketplace."""
        clause, params = self._scope("r", marketplace, None)
        rows = query_dicts(self._ch, f"{_LATEST_RULES}{clause} ORDER BY r.updated_at", params)
        latest: dict[tuple[str, str], PriceRule] = {}
        for r in rows:
            rule = PriceRule(
                **{**r, "is_active": bool(r["is_active"]), "dry_run": bool(r["dry_run"])}
            )
            latest[(rule.account_id, rule.product_id)] = rule
        return latest

    def import_targets(self, marketplace: str, text: str) -> TargetPriceImportResult:
        """Desired buyer prices of one marketplace from ``article;price`` lines.

        A card's latest rule is updated (it keeps its live / simulation state); a card without
        one gets a new rule in simulation. Articles with no card on the marketplace are listed.
        """
        prices, errors = parse_article_table(text, "цена")
        if not prices:
            return TargetPriceImportResult(imported=0, errors=errors)
        clause, params = self._scope("p", marketplace, None)
        cards = query_dicts(
            self._ch,
            "SELECT DISTINCT p.account_id AS account_id, p.offer_id AS offer_id"
            f" FROM mrt_price_current AS p FINAL{clause}"
            " AND p.offer_id IN {offers:Array(String)}",
            {**params, "offers": list(prices)},
        )
        existing = self._latest_rules(marketplace)
        now = utc_now()
        rules: list[PriceRule] = []
        for card in cards:
            key = (card["account_id"], card["offer_id"])
            price = prices[card["offer_id"]]
            rule = existing.get(key)
            if rule is not None:
                rules.append(
                    rule.model_copy(
                        update={
                            "mode": "buyer_price",
                            "target_price": price,
                            "is_active": True,
                            "created_at": rule.created_at or now,
                            "updated_at": now,
                        }
                    )
                )
            else:
                rules.append(
                    PriceRule(
                        rule_id=str(uuid.uuid4()),
                        marketplace=marketplace,
                        account_id=card["account_id"],
                        product_id=card["offer_id"],
                        mode="buyer_price",
                        target_price=price,
                        no_discount_fallback=default_fallback(marketplace),
                        dry_run=True,
                        created_at=now,
                        updated_at=now,
                    )
                )
        RepricerService(self._ch, self._org).write_rules(rules)
        found = {card["offer_id"] for card in cards}
        not_found = sorted(offer for offer in prices if offer not in found)
        return TargetPriceImportResult(
            imported=len(found),
            errors=errors,
            not_found=not_found[:_MAX_IMPORT_ERRORS],
            updated=sorted(found),
        )

    def keep_prices(self, marketplace: str, keep: bool) -> int:
        """Switch every desired-price rule of the marketplace live (``keep``) or to simulation."""
        now = utc_now()
        rules = [
            rule.model_copy(update={"dry_run": not keep, "is_active": True, "updated_at": now})
            for rule in self._latest_rules(marketplace).values()
            if rule.mode == "buyer_price" and rule.target_price > 0
        ]
        RepricerService(self._ch, self._org).write_rules(rules)
        return len(rules)

    def list_costs(self) -> list[OfferCost]:
        # the photo and name of the article from its card on any marketplace
        clause, params = self._scope("p", None, None)
        rows = query_dicts(
            self._ch,
            "SELECT c.offer_id AS offer_id, c.cost_price_rub AS cost_price_rub,"
            " c.updated_at AS updated_at, card.title AS title, card.image_url AS image_url"
            " FROM dim_offer_cost AS c FINAL"
            " LEFT JOIN (SELECT p.offer_id AS offer_id,"
            " anyIf(p.title, p.title != '') AS title,"
            " anyIf(p.image_url, p.image_url != '') AS image_url"
            f" FROM mrt_price_current AS p FINAL{clause} GROUP BY p.offer_id) AS card"
            " ON card.offer_id = c.offer_id"
            " WHERE c.organization_id = {oid:String} ORDER BY c.offer_id",
            params,
            settings={"join_use_nulls": 1},
        )
        return [
            OfferCost(
                offer_id=r["offer_id"],
                cost_price_rub=float(r["cost_price_rub"]),
                updated_at=str(r["updated_at"]),
                title=r.get("title") or None,
                image_url=r.get("image_url") or None,
            )
            for r in rows
        ]

    def set_costs(self, costs: dict[str, float]) -> int:
        if not costs:
            return 0
        now = utc_now()
        self._ch.insert(
            "dim_offer_cost",
            [[self._org, offer, float(cost), now] for offer, cost in costs.items()],
            column_names=["organization_id", "offer_id", "cost_price_rub", "updated_at"],
        )
        return len(costs)

    def delete_cost(self, offer_id: str) -> bool:
        exists = self._ch.query(
            "SELECT count() FROM dim_offer_cost FINAL"
            " WHERE organization_id = {oid:String} AND offer_id = {offer:String}",
            parameters={"oid": self._org, "offer": offer_id},
        ).result_rows[0][0]
        if not exists:
            return False
        self._ch.command(
            "ALTER TABLE dim_offer_cost DELETE"
            " WHERE organization_id = {oid:String} AND offer_id = {offer:String}",
            parameters={"oid": self._org, "offer": offer_id},
        )
        return True

    def import_costs(self, text: str) -> OfferCostImportResult:
        costs, errors = parse_article_table(text, "себестоимость")
        return OfferCostImportResult(
            imported=self.set_costs(costs), errors=errors, updated=sorted(costs)
        )


def parse_article_table(text: str, value_name: str) -> tuple[dict[str, float], list[str]]:
    """Parse ``article<sep>value`` lines pasted from a spreadsheet (a cost or a price).

    The separator is ``;``, tab or ``,`` (the first one found in a line); a decimal comma, spaces
    and a rouble sign in the value are accepted. A first line whose value is not a number is
    taken as a header. A line with an empty value (a blank cell of a template) is skipped. A
    later line for the same article wins. Errors are in Russian, for the UI, and name the value
    as ``value_name``.
    """
    values: dict[str, float] = {}
    errors: list[str] = []
    first = True
    for number, raw in enumerate(text.splitlines(), start=1):
        # spaces only: a trailing tab separates an empty cell
        line = raw.strip(" \r\n")
        if not line.strip():
            continue
        is_first, first = first, False
        sep = next((s for s in _SEPARATORS if s in line), None)
        if sep is None:
            _add_error(errors, f"строка {number}: нет второго столбца")
            continue
        offer, _, value_text = line.partition(sep)
        offer = offer.strip().strip('"')
        if not value_text.strip().strip('"'):
            continue
        value = _parse_number(value_text if sep != "," else value_text.replace(",", "."))
        if value is None:
            if not is_first:
                _add_error(errors, f"строка {number}: {value_name} — не число")
            continue
        if not offer or len(offer) > 128:
            _add_error(errors, f"строка {number}: неверный артикул")
            continue
        if value <= 0:
            _add_error(errors, f"строка {number}: {value_name} должна быть больше нуля")
            continue
        values[offer] = value
    return values, errors


def _parse_number(text: str) -> float | None:
    # drop spaces, currency signs and words ("1 250,50 RUB"), keep the number
    cleaned = re.sub(r"[^0-9,.\-]", "", text).replace(",", ".")
    if not re.search(r"[0-9]", cleaned):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _add_error(errors: list[str], message: str) -> None:
    if len(errors) < _MAX_IMPORT_ERRORS:
        errors.append(message)


def _opt_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _discount_usable(r: dict[str, Any]) -> bool:
    """Whether the repricer sets a buyer price on the card's measured discount: the card's own
    sales (3+ on WB, any on Ozon), or on WB the account's median over 10+ orders
    (workers/app/tasks/repricer.py)."""
    samples = int(r.get("mp_discount_samples") or 0)
    if r.get("mp_discount_scope") == "product":
        return samples >= (1 if r["marketplace"] == "ozon" else 3)
    return r.get("mp_discount_scope") == "account" and r["marketplace"] == "wb" and samples >= 10


def _breakdown_row(r: dict[str, Any]) -> PriceBreakdownRow:
    mode = r.get("mode")
    target = _opt_float(r.get("target_price"))
    fallback = r.get("no_discount_fallback") or ""
    if mode == "buyer_price" and fallback == "seller_price" and not _discount_usable(r):
        # the rule keeps the target as the seller price until the discount is measured
        mode_kept = "seller_price"
    else:
        mode_kept = mode or ""
    kept = {"buyer_price": r.get("buyer_price"), "seller_price": r.get("seller_price")}.get(
        mode_kept
    )
    gap = None
    if target and kept is not None:
        gap = round((float(kept) - target) / target * 100, 2)
    auto = r.get("auto_actions_enabled")
    return PriceBreakdownRow(
        marketplace=r["marketplace"],
        account_id=r["account_id"],
        offer_id=r["offer_id"],
        product_id=r["product_id"],
        title=r.get("title"),
        image_url=r.get("image_url"),
        list_price=float(r["list_price"]),
        seller_discount_pct=float(r["seller_discount_pct"]),
        seller_price=float(r["seller_price"]),
        mp_discount_pct=_opt_float(r.get("mp_discount_pct")),
        mp_discount_scope=r.get("mp_discount_scope") or "",
        mp_discount_samples=int(r.get("mp_discount_samples") or 0),
        buyer_price=_opt_float(r.get("buyer_price")),
        commission_pct=float(r["commission_pct"]),
        commission_rub=float(r["commission_rub"]),
        acquiring_rub=float(r["acquiring_rub"]),
        logistics_rub=float(r["logistics_rub"]),
        fees_rub=float(r["fees_rub"]),
        cost_price=_opt_float(r.get("cost_price")),
        margin_rub=_opt_float(r.get("margin_rub")),
        margin_pct=_opt_float(r.get("margin_pct")),
        breakeven_price=_opt_float(r.get("breakeven_price")),
        min_price=_opt_float(r.get("min_price")),
        auto_actions_enabled=None if auto is None else bool(auto),
        price_index_color=r.get("price_index_color") or "",
        price_seen_at=str(r["price_seen_at"]) if r.get("price_seen_at") else None,
        rule_id=r.get("rule_id") or None,
        mode=mode or None,
        target_price=target if r.get("rule_id") else None,
        no_discount_fallback=fallback if r.get("rule_id") else None,
        rule_is_active=None if not r.get("rule_id") else bool(r.get("rule_is_active")),
        rule_dry_run=None if not r.get("rule_id") else bool(r.get("rule_dry_run")),
        target_gap_pct=gap if r.get("rule_id") else None,
    )


def _compare_row(r: dict[str, Any]) -> PriceCompareRow:
    def present(key: str, flag: str) -> float | None:
        return _opt_float(r.get(key)) if r.get(flag) else None

    row = PriceCompareRow(
        offer_id=r["offer_id"],
        title=r.get("title"),
        image_url=r.get("image_url"),
        wb_seller_price=present("wb_seller_price", "on_wb"),
        wb_buyer_price=present("wb_buyer_price", "on_wb"),
        ozon_seller_price=present("ozon_seller_price", "on_ozon"),
        ozon_buyer_price=present("ozon_buyer_price", "on_ozon"),
    )
    buyer = [p for p in (row.wb_buyer_price, row.ozon_buyer_price) if p]
    if len(buyer) > 1:
        row.buyer_spread_pct = round((max(buyer) - min(buyer)) / min(buyer) * 100, 2)
    return row

"""High-performance O(N + S) article-level unit economics engine and accrual reader.

Key architectural invariants:
1. Composite key ``ArticleKey = tuple[str, str]`` -> ``(account_id, sku)`` prevents
   cross-account SKU collisions (Copilot #8).
2. Accrual line items return their exact monetary delta in O(1) without re-scanning
   the SKU dictionary on every operation, reducing complexity from O(N * S) to O(N + S)
   (Copilot #18).
3. Taxes are allocated strictly within the account(s) they belong to (Copilot #10),
   preserving the upstream tax status ('realization' | 'estimated' | 'disabled')
   (Copilot #11).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

ZERO = Decimal(0)
CENT = Decimal("0.01")
EXPENSES = (
    "delivery",
    "partners",
    "promotion",
    "fbo",
    "other_services",
    "compensation",
    "other_accruals",
    "marketing",
)
MARKETING = {
    3,
    4,
    5,
    19,
    23,
    31,
    33,
    41,
    47,
    48,
    49,
    50,
    54,
    55,
    61,
    70,
    75,
    80,
    87,
    95,
    96,
    116,
    130,
}
DELIVERY = {
    2,
    6,
    9,
    28,
    29,
    30,
    32,
    40,
    45,
    53,
    59,
    62,
    64,
    65,
    67,
    71,
    73,
    98,
    99,
    100,
    110,
    111,
    112,
    113,
    114,
    115,
    120,
    121,
    124,
}
PARTNERS = {1, 13, 16, 17, 42, 43, 44, 56, 63, 66, 68, 97, 106, 107, 108, 109, 122, 123}
FBO = {12, 21, 46, 58, 60, 77, 78, 79, 101, 102, 103, 131, 132, 133, 134, 135}
COMPENSATION = {10, 25, 81, 104}


def number(value: Any) -> Decimal:
    if isinstance(value, dict):
        value = value.get("amount")
    if value is None:
        return ZERO
    val_str = str(value).replace("\u00a0", "").replace(" ", "").replace(",", ".")
    try:
        result = Decimal(val_str)
    except Exception as exc:
        raise ValueError(f"Invalid decimal value: {value}") from exc
    if not result.is_finite():
        raise ValueError("Non-finite financial amount")
    return result


def category(type_id: Any) -> str:
    n = int(type_id or 0)
    return (
        "marketing"
        if n in MARKETING
        else "delivery"
        if n in DELIVERY
        else "partners"
        if n in PARTNERS
        else "fbo"
        if n in FBO
        else "compensation"
        if n in COMPENSATION
        else "other_services"
    )


def metric_row(values: Mapping[str, Any]) -> dict[str, Any]:
    """All unit averages and ratios use the totals; never average article percentages."""
    r = dict(values)
    cis_q = r.get("cis_qty", r.get("sales_cis", ZERO)) or ZERO
    qty = r.get("sales_qty", ZERO) + r.get("returns_qty", ZERO) + cis_q
    r["qty"] = qty
    r["mp_cost"] = sum(r.get(k, ZERO) for k in EXPENSES if k != "marketing")
    r["operating"] = (
        None
        if r.get("cogs") is None
        else r["revenue"] - r["commission"] - r["cogs"] - r["mp_cost"] - r.get("marketing", ZERO)
    )
    r["profit"] = (
        None
        if r["operating"] is None or r.get("tax") is None or r.get("external") is None
        else r["operating"] - r["external"] - r["tax"]
    )
    money_keys = (
        "revenue",
        "buyer_revenue",
        "commission",
        "cogs",
        "mp_cost",
        *EXPENSES,
        "operating",
        "external",
        "tax",
        "profit",
    )
    for key in money_keys:
        value = r.get(key)
        r[key + "_unit"] = value / qty if value is not None and qty > 0 else None
        r[key + "_pct"] = (
            value / r["revenue"] if value is not None and r.get("revenue", ZERO) > 0 else None
        )
    r["roi"] = (
        r["profit"] / r["cogs"]
        if r["profit"] is not None and r.get("cogs") and r["cogs"] > 0
        else None
    )
    return r


class AccrualEconomics:
    """Incremental O(N + S) reader for signed Ozon accrual payloads."""

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(lambda: ZERO))
        self.pool: dict[str, Decimal] = defaultdict(lambda: ZERO)
        self.raw_total: Decimal = ZERO
        self.operations: int = 0
        self.sale_days: dict[str, dict[str, Decimal]] = defaultdict(
            lambda: defaultdict(lambda: ZERO)
        )
        self.campaign_charges: dict[tuple[str, str], Decimal] = defaultdict(lambda: ZERO)
        self.domestic_sales: dict[tuple[str, str], dict[str, Any]] = defaultdict(
            lambda: defaultdict(lambda: ZERO)
        )
        self.buyout_receipts: Decimal = ZERO
        self.buyout_overlap_count: int = 0
        self.cis_sale_days: dict[str, dict[str, Decimal]] = defaultdict(
            lambda: defaultdict(lambda: ZERO)
        )
        self.seen_buyouts: dict[tuple[str, str], dict[str, Any]] = {}
        self._running_net: Decimal = ZERO

    def fee(self, sku: str | None, fee: dict[str, Any]) -> Decimal:
        amt = number(fee.get("accrued"))
        cat = category(fee.get("type_id"))
        if sku:
            self.rows[str(sku)][cat] -= amt
        else:
            self.pool[cat] -= amt
        return amt

    def add(self, payload: dict[str, Any]) -> None:
        total_amount = number(payload.get("total_amount"))
        self.raw_total += total_amount
        self.operations += 1
        posting = payload.get("posting") or {}
        delta = ZERO

        for p in posting.get("products") or []:
            sku = str(p.get("sku") or "")
            if not sku:
                continue
            row = self.rows[sku]
            commission = p.get("commission") or {}
            revenue = number(commission.get("sale_amount"))
            if revenue:
                qty = number(p.get("quantity") or 1)
                signed_qty = -qty if revenue < 0 else qty
                row["sales_qty" if revenue > 0 else "returns_qty"] += signed_qty
                row["revenue"] += revenue
                sale_price_val = abs(number(commission.get("sale_price"))) * signed_qty
                row["buyer_revenue"] += sale_price_val
                row["revenue_rf"] += revenue
                row["buyer_rf"] += sale_price_val
                comm_val = number(commission.get("commission"))
                row["commission_rf"] -= comm_val
                self.sale_days[sku][str(payload["date"])[:7]] += sale_price_val
                row["commission"] -= comm_val
                delta += revenue + comm_val
                if revenue > 0 and payload.get("unit_number"):
                    original = self.domestic_sales[(str(payload["unit_number"]), sku)]
                    original["quantity"] += qty
                    original["gross"] += revenue
                    original["receipt"] += abs(number(commission.get("sale_price"))) * qty
                    original["deduction"] -= comm_val

            delivery = p.get("delivery") or {}
            services = delivery.get("services") or []
            for fee in services:
                delta += self.fee(sku, fee)
            tot_acc = number(delivery.get("total_accrued"))
            svc_sum = sum((number(f.get("accrued")) for f in services), ZERO)
            diff = tot_acc - svc_sum
            row["other_services"] -= diff
            delta += diff

        for item in (payload.get("item_fees") or {}).get("fees") or []:
            for fee in item.get("fees") or []:
                delta += self.fee(item.get("sku"), fee)

        non_item = payload.get("non_item_fee")
        if non_item:
            delta += self.fee(None, non_item)
            if int(non_item.get("type_id") or 0) in {41, 75}:
                self.campaign_charges[
                    (str(payload.get("date")), str(payload.get("unit_number")))
                ] -= number(non_item.get("accrued"))

        for fee in (payload.get("container_fees") or {}).get("fees") or []:
            delta += self.fee(None, fee)

        remainder = total_amount - delta
        self.pool["other_accruals"] -= remainder
        self._running_net += total_amount

    def net(self) -> Decimal:
        return sum(
            (
                r["revenue"] - r["commission"] - sum((r[e] for e in EXPENSES), ZERO)
                for r in self.rows.values()
            ),
            ZERO,
        ) - sum(self.pool.values(), ZERO)

    def add_buyouts(self, day: Any, payload: dict[str, Any]) -> None:
        from .ozon_buyouts import parse_buyouts

        for record in parse_buyouts(payload):
            identity = (record["posting_number"], record["sku"])
            if identity in self.seen_buyouts:
                if self.seen_buyouts[identity] != record:
                    raise ValueError("Conflicting buyout rows for the same posting/SKU")
                self.buyout_overlap_count += 1
                continue
            self.seen_buyouts[identity] = record
            sku = record["sku"]
            row = self.rows[sku]
            original = self.domestic_sales.get((record["posting_number"], sku))
            if original:
                self.buyout_overlap_count += 1
                row["sales_qty"] -= original["quantity"]
                row["sales_cis"] += original["quantity"]
                for target, field_name in [
                    ("revenue", "gross"),
                    ("buyer", "receipt"),
                    ("commission", "deduction"),
                ]:
                    row[target + "_rf"] -= original[field_name]
                    row[target + "_cis"] += original[field_name]
                continue
            row["sales_cis"] += record["quantity"]
            row["revenue"] += record["gross"]
            row["revenue_cis"] += record["gross"]
            row["buyer_revenue"] += record["receipt"]
            row["buyer_cis"] += record["receipt"]
            row["commission"] += record["deduction"]
            row["commission_cis"] += record["deduction"]
            self.sale_days[sku][str(day)[:7]] += record["receipt"]
            self.cis_sale_days[sku][str(day)[:7]] += record["receipt"]
            self.buyout_receipts += record["receipt"]
            self.raw_total += record["receipt"]

    def allocate(self) -> dict[str, Decimal]:
        original_pool = dict(self.pool)
        for key, amount in original_pool.items():
            if amount:
                self.rows["unallocated"][key] += amount
        self.pool.clear()
        if abs(self.net() - self.raw_total) > CENT:
            raise ValueError("Article attribution does not reconcile to the raw accruals")
        return original_pool

    def bind_ad_costs(self, records: Iterable[Any]) -> tuple[Decimal, int]:
        linked = ZERO
        matched = set()
        for day, campaign, sku, cost in records:
            key = (str(day), str(campaign))
            if key not in self.campaign_charges:
                continue
            amount = number(cost)
            if amount:
                self.rows[str(sku)]["marketing"] += amount
                self.rows["unallocated"]["marketing"] -= amount
                linked += amount
                matched.add(key)
        if abs(self.net() - self.raw_total) > CENT:
            raise ValueError("Performance binding changed the source finance total")
        return linked, len(matched)


# (account_id, sku_or_product_id)
type ArticleKey = tuple[str, str]


@dataclass
class ArticleAccumulator:
    """Mutable O(1) per-article accumulator scoped to a single (account_id, sku)."""

    account_id: str
    marketplace: str
    sku: str
    offer_id: str = ""
    title: str = ""
    image_url: str | None = None
    cost_price_rub: float | None = None

    sales_qty: int = 0
    returns_qty: int = 0
    sales_rub: float = 0.0
    returns_rub: float = 0.0
    commission_rub: float = 0.0
    acquiring_rub: float = 0.0
    logistics_rub: float = 0.0
    reverse_logistics_rub: float = 0.0
    storage_rub: float = 0.0
    other_mp_fees_rub: float = 0.0
    direct_ad_cost_rub: float = 0.0

    @property
    def net_qty(self) -> int:
        return self.sales_qty - self.returns_qty

    @property
    def net_revenue_rub(self) -> float:
        return self.sales_rub - abs(self.returns_rub)

    @property
    def total_mp_fees_rub(self) -> float:
        """Signed sum of marketplace deductions (negative when charges exceed compensations)."""
        return (
            self.commission_rub
            + self.acquiring_rub
            + self.logistics_rub
            + self.reverse_logistics_rub
            + self.storage_rub
            + self.other_mp_fees_rub
        )

    @property
    def net_accrued_before_unallocated_rub(self) -> float:
        """O(1) net accrued directly attributed to this SKU."""
        return self.sales_rub - abs(self.returns_rub) + self.total_mp_fees_rub


@dataclass(frozen=True)
class ArticleEconomicsRow:
    """Finalized unit economics row ready for API serialization or aggregation."""

    marketplace: str
    account_id: str
    sku: str
    offer_id: str
    title: str
    image_url: str | None
    sales_qty: int
    returns_qty: int
    net_qty: int
    sales_rub: float
    returns_rub: float
    net_revenue_rub: float
    commission_rub: float
    acquiring_rub: float
    logistics_rub: float
    reverse_logistics_rub: float
    storage_rub: float
    other_mp_fees_rub: float
    allocated_mp_overhead_rub: float
    net_accrued_rub: float
    unit_cost_rub: float | None
    cogs_rub: float
    missing_cost: bool
    direct_ad_cost_rub: float
    allocated_ad_cost_rub: float
    total_ad_cost_rub: float
    gross_profit_rub: float
    allocated_indirect_expenses_rub: float
    operating_profit_rub: float
    allocated_tax_rub: float
    net_profit_rub: float
    margin_pct: float
    markup_pct: float | None
    abc_revenue_class: str = "C"
    abc_profit_class: str = "C"


@dataclass(frozen=True)
class ArticleEconomicsReport:
    """Complete report with rows, totals, and data-quality flags."""

    items: list[ArticleEconomicsRow]
    missing_cost_offers: list[str]
    tax_status: str
    tax_enabled: bool
    total_revenue_rub: float
    total_net_accrued_rub: float
    total_cogs_rub: float
    total_ad_cost_rub: float
    total_indirect_expenses_rub: float
    total_tax_rub: float
    total_net_profit_rub: float


@dataclass
class ArticleEconomicsEngine:
    """O(N + S) streaming accumulator for article-level unit economics."""

    _items: dict[ArticleKey, ArticleAccumulator] = field(default_factory=dict)
    _offer_to_sku: dict[tuple[str, str], str] = field(default_factory=dict)
    _unallocated_mp_by_account: defaultdict[str, float] = field(
        default_factory=lambda: defaultdict(float)
    )
    _unallocated_ad_by_account: defaultdict[str, float] = field(
        default_factory=lambda: defaultdict(float)
    )
    _running_attributed_net: float = 0.0

    def register_card(
        self,
        *,
        account_id: str,
        marketplace: str,
        sku: str,
        offer_id: str = "",
        title: str = "",
        image_url: str | None = None,
        cost_price_rub: float | None = None,
    ) -> ArticleAccumulator:
        """Register or enrich a product card under composite key (account_id, sku)."""
        norm_sku = str(sku).strip()
        norm_offer = str(offer_id).strip()
        key: ArticleKey = (account_id, norm_sku)
        acc = self._items.get(key)
        if acc is None:
            acc = ArticleAccumulator(
                account_id=account_id,
                marketplace=marketplace,
                sku=norm_sku,
                offer_id=norm_offer,
                title=title,
                image_url=image_url,
                cost_price_rub=cost_price_rub,
            )
            self._items[key] = acc
        else:
            if norm_offer and not acc.offer_id:
                acc.offer_id = norm_offer
            if title and not acc.title:
                acc.title = title
            if image_url and not acc.image_url:
                acc.image_url = image_url
            if cost_price_rub is not None and cost_price_rub > 0:
                acc.cost_price_rub = cost_price_rub

        if norm_offer:
            self._offer_to_sku[(account_id, norm_offer)] = norm_sku
        return acc

    def resolve_sku(self, account_id: str, sku_or_offer: str) -> str:
        """Resolve an offer_id to its canonical SKU within the same account."""
        candidate = str(sku_or_offer).strip()
        if (account_id, candidate) in self._items:
            return candidate
        return self._offer_to_sku.get((account_id, candidate), candidate)

    def add_line_movement(
        self,
        *,
        account_id: str,
        marketplace: str,
        sku: str,
        offer_id: str = "",
        title: str = "",
        sales_qty: int = 0,
        returns_qty: int = 0,
        sales_rub: float = 0.0,
        returns_rub: float = 0.0,
        commission_rub: float = 0.0,
        acquiring_rub: float = 0.0,
        logistics_rub: float = 0.0,
        reverse_logistics_rub: float = 0.0,
        storage_rub: float = 0.0,
        other_mp_fees_rub: float = 0.0,
    ) -> float:
        """Apply a single item movement in O(1) time and return its exact net delta."""
        resolved_sku = self.resolve_sku(account_id, sku or offer_id)
        acc = self.register_card(
            account_id=account_id,
            marketplace=marketplace,
            sku=resolved_sku,
            offer_id=offer_id,
            title=title,
        )
        acc.sales_qty += int(sales_qty)
        acc.returns_qty += int(returns_qty)
        acc.sales_rub += float(sales_rub)
        acc.returns_rub += abs(float(returns_rub))
        acc.commission_rub += float(commission_rub)
        acc.acquiring_rub += float(acquiring_rub)
        acc.logistics_rub += float(logistics_rub)
        acc.reverse_logistics_rub += float(reverse_logistics_rub)
        acc.storage_rub += float(storage_rub)
        acc.other_mp_fees_rub += float(other_mp_fees_rub)

        delta = (
            float(sales_rub)
            - abs(float(returns_rub))
            + float(commission_rub)
            + float(acquiring_rub)
            + float(logistics_rub)
            + float(reverse_logistics_rub)
            + float(storage_rub)
            + float(other_mp_fees_rub)
        )
        self._running_attributed_net += delta
        return delta

    def process_accrual_operation(
        self,
        *,
        account_id: str,
        marketplace: str,
        total_operation_amount: float,
        line_items: Iterable[Mapping[str, Any]],
    ) -> float:
        """Process one accrual operation in O(k) where k is items in the posting (not O(S))."""
        attributed_delta = 0.0
        for item in line_items:
            attributed_delta += self.add_line_movement(
                account_id=account_id,
                marketplace=marketplace,
                sku=str(item.get("sku") or ""),
                offer_id=str(item.get("offer_id") or ""),
                title=str(item.get("title") or ""),
                sales_qty=int(item.get("sales_qty") or 0),
                returns_qty=int(item.get("returns_qty") or 0),
                sales_rub=float(item.get("sales_rub") or 0.0),
                returns_rub=float(item.get("returns_rub") or 0.0),
                commission_rub=float(item.get("commission_rub") or 0.0),
                acquiring_rub=float(item.get("acquiring_rub") or 0.0),
                logistics_rub=float(item.get("logistics_rub") or 0.0),
                reverse_logistics_rub=float(item.get("reverse_logistics_rub") or 0.0),
                storage_rub=float(item.get("storage_rub") or 0.0),
                other_mp_fees_rub=float(item.get("other_mp_fees_rub") or 0.0),
            )
        remainder = float(total_operation_amount) - attributed_delta
        if abs(remainder) >= 0.005:
            self._unallocated_mp_by_account[account_id] += remainder
        return attributed_delta

    def add_unallocated_mp_fee(self, account_id: str, amount_rub: float) -> None:
        """Record an account-level marketplace fee/compensation not tied to a single SKU."""
        self._unallocated_mp_by_account[account_id] += float(amount_rub)

    def add_sku_ad_cost(
        self,
        *,
        account_id: str,
        marketplace: str,
        sku: str,
        cost_rub: float,
        offer_id: str = "",
    ) -> None:
        """Attribute direct SKU advertising spend in O(1)."""
        resolved_sku = self.resolve_sku(account_id, sku or offer_id)
        acc = self.register_card(
            account_id=account_id,
            marketplace=marketplace,
            sku=resolved_sku,
            offer_id=offer_id,
        )
        acc.direct_ad_cost_rub += abs(float(cost_rub))

    def add_unallocated_ad_cost(self, account_id: str, cost_rub: float) -> None:
        """Record campaign ad spend that could not be attributed to a specific SKU."""
        self._unallocated_ad_by_account[account_id] += abs(float(cost_rub))

    def finalize(
        self,
        *,
        indirect_expenses_rub: float = 0.0,
        tax_by_account: Mapping[str, float] | None = None,
        tax_status: str = "disabled",
        tax_enabled: bool = False,
        merge_accounts: bool = False,
    ) -> ArticleEconomicsReport:
        """Single O(S log S) finalization pass to allocate overheads, taxes, and ABC classes."""
        taxes = dict(tax_by_account or {})
        active_accumulators = [
            acc
            for acc in self._items.values()
            if (
                acc.sales_qty > 0
                or acc.returns_qty > 0
                or abs(acc.sales_rub) > 0.005
                or abs(acc.total_mp_fees_rub) > 0.005
                or acc.direct_ad_cost_rub > 0.005
            )
        ]

        # 1. Compute revenue weights per account and globally in O(S)
        account_revenue: defaultdict[str, float] = defaultdict(float)
        account_counts: defaultdict[str, int] = defaultdict(int)
        for acc in active_accumulators:
            rev = max(0.0, acc.net_revenue_rub)
            account_revenue[acc.account_id] += rev
            account_counts[acc.account_id] += 1

        total_org_revenue = sum(account_revenue.values())
        total_active_count = len(active_accumulators)

        def _account_share(acc: ArticleAccumulator) -> float:
            acct_rev = account_revenue[acc.account_id]
            if acct_rev > 0:
                return max(0.0, acc.net_revenue_rub) / acct_rev
            cnt = account_counts[acc.account_id]
            return (1.0 / cnt) if cnt > 0 else 0.0

        def _org_share(acc: ArticleAccumulator) -> float:
            if total_org_revenue > 0:
                return max(0.0, acc.net_revenue_rub) / total_org_revenue
            return (1.0 / total_active_count) if total_active_count > 0 else 0.0

        # 2. Build finalized rows per (account_id, sku)
        missing_cost_offers: set[str] = set()
        raw_rows: list[ArticleEconomicsRow] = []

        for acc in active_accumulators:
            acct_w = _account_share(acc)
            org_w = _org_share(acc)

            alloc_mp_overhead = self._unallocated_mp_by_account.get(acc.account_id, 0.0) * acct_w
            net_accrued = acc.net_accrued_before_unallocated_rub + alloc_mp_overhead

            alloc_ad = self._unallocated_ad_by_account.get(acc.account_id, 0.0) * acct_w
            total_ad = acc.direct_ad_cost_rub + alloc_ad

            has_activity = acc.sales_qty > 0 or acc.returns_qty > 0
            cost_missing = has_activity and (acc.cost_price_rub is None or acc.cost_price_rub <= 0)
            if cost_missing:
                missing_cost_offers.add(acc.offer_id or acc.sku)

            unit_cost = (
                acc.cost_price_rub if (acc.cost_price_rub and acc.cost_price_rub > 0) else None
            )
            cogs = (unit_cost * acc.net_qty) if unit_cost is not None else 0.0

            gross_profit = net_accrued - cogs
            alloc_indirect = float(indirect_expenses_rub) * org_w
            operating_profit = gross_profit - total_ad - alloc_indirect

            # Strictly scope tax to its target account_id (Fixes Copilot #10)
            acct_tax_pool = abs(float(taxes.get(acc.account_id, 0.0)))
            alloc_tax = acct_tax_pool * acct_w
            net_profit = operating_profit - alloc_tax

            net_rev = acc.net_revenue_rub
            margin_pct = round((net_profit / net_rev) * 100.0, 2) if net_rev > 0 else 0.0
            markup_pct = round((net_profit / cogs) * 100.0, 2) if cogs > 0 else None

            raw_rows.append(
                ArticleEconomicsRow(
                    marketplace=acc.marketplace,
                    account_id=acc.account_id,
                    sku=acc.sku,
                    offer_id=acc.offer_id or acc.sku,
                    title=acc.title,
                    image_url=acc.image_url,
                    sales_qty=acc.sales_qty,
                    returns_qty=acc.returns_qty,
                    net_qty=acc.net_qty,
                    sales_rub=round(acc.sales_rub, 2),
                    returns_rub=round(abs(acc.returns_rub), 2),
                    net_revenue_rub=round(net_rev, 2),
                    commission_rub=round(acc.commission_rub, 2),
                    acquiring_rub=round(acc.acquiring_rub, 2),
                    logistics_rub=round(acc.logistics_rub, 2),
                    reverse_logistics_rub=round(acc.reverse_logistics_rub, 2),
                    storage_rub=round(acc.storage_rub, 2),
                    other_mp_fees_rub=round(acc.other_mp_fees_rub, 2),
                    allocated_mp_overhead_rub=round(alloc_mp_overhead, 2),
                    net_accrued_rub=round(net_accrued, 2),
                    unit_cost_rub=round(unit_cost, 2) if unit_cost is not None else None,
                    cogs_rub=round(cogs, 2),
                    missing_cost=cost_missing,
                    direct_ad_cost_rub=round(acc.direct_ad_cost_rub, 2),
                    allocated_ad_cost_rub=round(alloc_ad, 2),
                    total_ad_cost_rub=round(total_ad, 2),
                    gross_profit_rub=round(gross_profit, 2),
                    allocated_indirect_expenses_rub=round(alloc_indirect, 2),
                    operating_profit_rub=round(operating_profit, 2),
                    allocated_tax_rub=round(alloc_tax, 2),
                    net_profit_rub=round(net_profit, 2),
                    margin_pct=margin_pct,
                    markup_pct=markup_pct,
                )
            )

        rows = _merge_across_accounts(raw_rows) if merge_accounts else raw_rows
        classified = _assign_abc_classes(rows)

        return ArticleEconomicsReport(
            items=classified,
            missing_cost_offers=sorted(missing_cost_offers),
            tax_status=tax_status,
            tax_enabled=tax_enabled,
            total_revenue_rub=round(sum(r.net_revenue_rub for r in classified), 2),
            total_net_accrued_rub=round(sum(r.net_accrued_rub for r in classified), 2),
            total_cogs_rub=round(sum(r.cogs_rub for r in classified), 2),
            total_ad_cost_rub=round(sum(r.total_ad_cost_rub for r in classified), 2),
            total_indirect_expenses_rub=round(
                sum(r.allocated_indirect_expenses_rub for r in classified), 2
            ),
            total_tax_rub=round(sum(r.allocated_tax_rub for r in classified), 2),
            total_net_profit_rub=round(sum(r.net_profit_rub for r in classified), 2),
        )


def _merge_across_accounts(rows: list[ArticleEconomicsRow]) -> list[ArticleEconomicsRow]:
    """Optional post-calculation aggregation by offer_id AFTER per-account COGS & tax."""
    grouped: dict[tuple[str, str], list[ArticleEconomicsRow]] = defaultdict(list)
    for row in rows:
        grouped[(row.marketplace, row.offer_id or row.sku)].append(row)

    merged: list[ArticleEconomicsRow] = []
    for (marketplace, offer_key), group in grouped.items():
        if len(group) == 1:
            merged.append(group[0])
            continue
        first = group[0]
        sales_qty = sum(r.sales_qty for r in group)
        returns_qty = sum(r.returns_qty for r in group)
        net_qty = sales_qty - returns_qty
        net_rev = sum(r.net_revenue_rub for r in group)
        cogs = sum(r.cogs_rub for r in group)
        net_profit = sum(r.net_profit_rub for r in group)
        merged.append(
            ArticleEconomicsRow(
                marketplace=marketplace,
                account_id="all",
                sku=first.sku,
                offer_id=offer_key,
                title=next((r.title for r in group if r.title), ""),
                image_url=next((r.image_url for r in group if r.image_url), None),
                sales_qty=sales_qty,
                returns_qty=returns_qty,
                net_qty=net_qty,
                sales_rub=round(sum(r.sales_rub for r in group), 2),
                returns_rub=round(sum(r.returns_rub for r in group), 2),
                net_revenue_rub=round(net_rev, 2),
                commission_rub=round(sum(r.commission_rub for r in group), 2),
                acquiring_rub=round(sum(r.acquiring_rub for r in group), 2),
                logistics_rub=round(sum(r.logistics_rub for r in group), 2),
                reverse_logistics_rub=round(sum(r.reverse_logistics_rub for r in group), 2),
                storage_rub=round(sum(r.storage_rub for r in group), 2),
                other_mp_fees_rub=round(sum(r.other_mp_fees_rub for r in group), 2),
                allocated_mp_overhead_rub=round(sum(r.allocated_mp_overhead_rub for r in group), 2),
                net_accrued_rub=round(sum(r.net_accrued_rub for r in group), 2),
                unit_cost_rub=(
                    round(cogs / net_qty, 2) if net_qty > 0 and cogs > 0 else first.unit_cost_rub
                ),
                cogs_rub=round(cogs, 2),
                missing_cost=any(r.missing_cost for r in group),
                direct_ad_cost_rub=round(sum(r.direct_ad_cost_rub for r in group), 2),
                allocated_ad_cost_rub=round(sum(r.allocated_ad_cost_rub for r in group), 2),
                total_ad_cost_rub=round(sum(r.total_ad_cost_rub for r in group), 2),
                gross_profit_rub=round(sum(r.gross_profit_rub for r in group), 2),
                allocated_indirect_expenses_rub=round(
                    sum(r.allocated_indirect_expenses_rub for r in group), 2
                ),
                operating_profit_rub=round(sum(r.operating_profit_rub for r in group), 2),
                allocated_tax_rub=round(sum(r.allocated_tax_rub for r in group), 2),
                net_profit_rub=round(net_profit, 2),
                margin_pct=round((net_profit / net_rev) * 100.0, 2) if net_rev > 0 else 0.0,
                markup_pct=round((net_profit / cogs) * 100.0, 2) if cogs > 0 else None,
            )
        )
    return merged


def _assign_abc_classes(rows: list[ArticleEconomicsRow]) -> list[ArticleEconomicsRow]:
    """Assign ABC classes by net revenue and by net profit in O(S log S)."""
    if not rows:
        return []

    def _classify(metric_fn: Any) -> dict[tuple[str, str, str], str]:
        ordered = sorted(
            rows,
            key=lambda r: (max(0.0, float(metric_fn(r))), r.net_revenue_rub),
            reverse=True,
        )
        total = sum(max(0.0, float(metric_fn(r))) for r in ordered)
        classes: dict[tuple[str, str, str], str] = {}
        cumulative = 0.0
        for r in ordered:
            key = (r.marketplace, r.account_id, r.sku)
            val = max(0.0, float(metric_fn(r)))
            if total <= 0 or val <= 0:
                classes[key] = "C"
                continue
            cumulative += val / total
            if cumulative <= 0.80:
                classes[key] = "A"
            elif cumulative <= 0.95:
                classes[key] = "B"
            else:
                classes[key] = "C"
        return classes

    rev_abc = _classify(lambda r: r.net_revenue_rub)
    prof_abc = _classify(lambda r: r.net_profit_rub)

    result = [
        ArticleEconomicsRow(
            **{
                **r.__dict__,
                "abc_revenue_class": rev_abc[(r.marketplace, r.account_id, r.sku)],
                "abc_profit_class": prof_abc[(r.marketplace, r.account_id, r.sku)],
            }
        )
        for r in rows
    ]
    return sorted(result, key=lambda r: (r.net_revenue_rub, r.net_profit_rub), reverse=True)

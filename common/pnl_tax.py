"""Opt-in SVOYO tax rule: net realization amount times the configured rate."""

from __future__ import annotations

import calendar
import os
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

CENT = Decimal("0.01")


def money(value: Any) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Invalid realization money value") from exc
    if not result.is_finite():
        raise ValueError("Non-finite realization amount")
    return result


def realization_totals(payload: dict[str, Any], month: date) -> tuple[Decimal, Decimal]:
    """Validate a closed monthly report; do not substitute payouts or seller list prices."""
    result = payload.get("result")
    if not isinstance(result, dict):
        raise ValueError("Realization report is unavailable: missing result")
    header = result.get("header") or {}
    last = month.replace(day=calendar.monthrange(month.year, month.month)[1])
    if (
        str(header.get("start_date"))[:10] != month.isoformat()
        or str(header.get("stop_date"))[:10] != last.isoformat()
    ):
        raise ValueError("Realization report period does not match requested month")
    if header.get("currency_sys_name") != "RUB":
        raise ValueError("Expected a RUB realization report")
    rows = result.get("rows")
    if not isinstance(rows, list):
        raise ValueError("Realization report rows are missing")
    sales, returns = Decimal(0), Decimal(0)
    seen: set[int] = set()
    for row in rows:
        row_num = row.get("rowNumber")
        if row_num is None or row_num in seen:
            raise ValueError("Missing or duplicate realization row number")
        seen.add(row_num)
        for field, is_return in [("delivery_commission", False), ("return_commission", True)]:
            section = row.get(field)
            if section is None:
                continue
            amount = money(section["amount"])
            if amount < 0:
                raise ValueError("Negative realization section amount")
            if is_return:
                returns += amount
            else:
                sales += amount
    return sales.quantize(CENT), returns.quantize(CENT)


def tax_amount(base: Decimal, rate: Decimal) -> Decimal:
    if not rate.is_finite() or not Decimal(0) <= rate <= Decimal(100):
        raise ValueError("Tax rate must be between 0 and 100 percent")
    return (max(base, Decimal(0)) * rate / Decimal(100)).quantize(CENT, rounding=ROUND_HALF_UP)


def is_tax_applicable(organization_id: str, marketplace: str, account_id: str) -> bool:
    """Return True if tax overlay is applicable to the given org, marketplace, and account."""
    if os.getenv("PNL_REALIZATION_TAX_ENABLED", "false").strip().lower() != "true":
        return False
    if organization_id.strip() != os.getenv("PNL_TAX_ORGANIZATION_ID", "default").strip():
        return False

    allowed_marketplaces = {
        m.strip().lower()
        for m in os.getenv("PNL_TAX_MARKETPLACES", "ozon,wb,ym").split(",")
        if m.strip()
    }
    mp = marketplace.strip().lower()
    if not mp or mp not in allowed_marketplaces:
        return False

    account_rule = os.getenv("PNL_TAX_ACCOUNT_ID", "default").strip()
    if account_rule.lower() in ("*", "all"):
        return True

    allowed_accounts = {a.strip() for a in account_rule.split(",") if a.strip()}
    aid = account_id.strip()
    pair = f"{mp}:{aid}"
    return aid in allowed_accounts or pair in allowed_accounts

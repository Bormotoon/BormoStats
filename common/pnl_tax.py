"""Opt-in SVOYO tax rule: net realization amount times the configured rate."""

from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

CENT = Decimal('0.01')


def money(value: Any) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError('Invalid realization money value') from exc
    if not result.is_finite():
        raise ValueError('Non-finite realization amount')
    return result


def realization_totals(payload: dict[str, Any], month: date) -> tuple[Decimal, Decimal]:
    """Validate a closed monthly report; do not substitute payouts or seller list prices."""
    result = payload.get('result')
    if not isinstance(result, dict):
        raise ValueError('Realization report is unavailable: missing result')
    header = result.get('header') or {}
    last = month.replace(day=calendar.monthrange(month.year, month.month)[1])
    if (str(header.get('start_date'))[:10] != month.isoformat()
            or str(header.get('stop_date'))[:10] != last.isoformat()):
        raise ValueError('Realization report period does not match requested month')
    if header.get('currency_sys_name') != 'RUB':
        raise ValueError('Expected a RUB realization report')
    rows = result.get('rows')
    if not isinstance(rows, list):
        raise ValueError('Realization report rows are missing')
    sales, returns = Decimal(0), Decimal(0)
    seen: set[int] = set()
    for row in rows:
        number = row.get('rowNumber')
        if number is None or number in seen:
            raise ValueError('Missing or duplicate realization row number')
        seen.add(number)
        for field, is_return in [('delivery_commission', False), ('return_commission', True)]:
            section = row.get(field)
            if section is None:
                continue
            amount = money(section['amount'])
            if amount < 0:
                raise ValueError('Negative realization section amount')
            if is_return:
                returns += amount
            else:
                sales += amount
    return sales.quantize(CENT), returns.quantize(CENT)


def tax_amount(base: Decimal, rate: Decimal) -> Decimal:
    if not rate.is_finite() or not Decimal(0) <= rate <= Decimal(100):
        raise ValueError('Tax rate must be between 0 and 100 percent')
    return (max(base, Decimal(0)) * rate / Decimal(100)).quantize(CENT, rounding=ROUND_HALF_UP)

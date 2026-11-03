"""Finance categories shared by the collectors, the marts and the API.

Every marketplace money movement of a day is put into one category, signed from the
seller's point of view (income positive, charges negative), so that

    sales + returns + commission + acquiring + logistics + reverse_logistics + storage
    + acceptance + penalties + other = net_accrued

where ``net_accrued`` is what the marketplace adds to the seller's balance for the day
(Ozon ``total.accrued``, WB "Итого к оплате" of the realization report). Payouts to the
seller's bank account are not part of the accrual: they move money off the balance.
"""

from __future__ import annotations

FINANCE_CATEGORIES: tuple[str, ...] = (
    "sales",  # goods sold, at the seller's price
    "returns",  # goods returned by buyers, at the seller's price (negative)
    "commission",  # marketplace commission (net of commission refunded on returns)
    "acquiring",  # payment processing
    "logistics",  # delivery to the buyer, last mile, handover
    "reverse_logistics",  # returns and cancellations: carriage back, processing
    "storage",  # warehouse placement
    "acceptance",  # paid acceptance and inbound operations
    "penalties",  # fines
    "other",  # everything else, positive compensations included
)


# Specific services precede generic words such as "return" and "payment".
YM_FINANCE_RULES: tuple[tuple[str, str], ...] = (
    ("payouts", r"payout|выплат|перечисление продавцу"),
    (
        "reverse_logistics",
        r"reverse|return.*(delivery|logistic|processing)|возвратная логист|невыкуп",
    ),
    ("commission", r"commission|(^| )fee( |$)|размещен|комисс"),
    ("acquiring", r"acquir|agency|payment_transfer|прием.*платеж|приём.*платеж"),
    ("logistics", r"delivery|logistic|sorting|достав|складская обработка"),
    ("storage", r"storage|хранен"),
    ("acceptance", r"accept|приемк|приёмк"),
    ("penalties", r"penalt|штраф"),
    (
        "other",
        r"boost|буст|продвижение|продвижен",
    ),  # boost/promotion as other, checked before sales
    ("returns", r"return|возврат"),
    ("sales", r"sale|продаж|платеж покупателя|платёж покупателя"),
)


def classify_ym_finance(transaction_type: str, service_type: str) -> str:
    """Classify a signed money movement without changing its sign."""
    import re

    text = f"{service_type} {transaction_type}".strip().lower()
    # Boost/promotion must not be classified as sales - check specific boost patterns first
    if re.search(r"буст\s+продаж|продаж.*буст|boost.*продаж", text):
        return "other"
    return next(
        (category for category, pattern in YM_FINANCE_RULES if re.search(pattern, text)), "other"
    )

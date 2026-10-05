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

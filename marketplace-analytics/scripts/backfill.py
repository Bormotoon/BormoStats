#!/usr/bin/env python3
"""Trigger backfill through admin API."""

from __future__ import annotations

import argparse
import os

import httpx

ALLOWED_BACKFILLS: dict[tuple[str, str], int] = {
    ("wb", "sales"): 90,
    ("wb", "orders"): 90,
    ("wb", "funnel"): 90,
    ("ozon", "postings"): 90,
    ("ozon", "finance"): 365,
    ("marts", "build"): 365,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Trigger backfill job via backend admin API")
    default_backend_port = os.getenv("BACKEND_HOST_PORT", "18080")
    parser.add_argument(
        "--base-url",
        default=os.getenv("ADMIN_BASE_URL", f"http://localhost:{default_backend_port}"),
    )
    parser.add_argument("--api-key", default=os.getenv("ADMIN_API_KEY", ""))
    parser.add_argument("--marketplace", required=True, choices=["wb", "ozon", "marts"])
    parser.add_argument(
        "--dataset",
        required=True,
        choices=["sales", "orders", "funnel", "postings", "finance", "build"],
    )
    parser.add_argument("--days", type=int, default=14)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.api_key:
        raise SystemExit("ADMIN_API_KEY is required")
    max_days = ALLOWED_BACKFILLS.get((args.marketplace, args.dataset))
    if max_days is None:
        raise SystemExit(f"unsupported backfill target: {args.marketplace}:{args.dataset}")
    if args.days < 1 or args.days > max_days:
        raise SystemExit(
            f"--days must be between 1 and {max_days} for {args.marketplace}:{args.dataset}"
        )

    url = f"{args.base_url.rstrip('/')}/api/v1/admin/backfill"
    payload = {
        "marketplace": args.marketplace,
        "dataset": args.dataset,
        "days": args.days,
    }

    with httpx.Client(timeout=30.0) as client:
        response = client.post(url, json=payload, headers={"X-API-Key": args.api_key})
        response.raise_for_status()
        print(response.text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

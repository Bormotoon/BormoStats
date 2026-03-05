#!/usr/bin/env python3
"""Validate required marketplace credentials in environment."""

from __future__ import annotations

import os
import sys

REQUIRED = [
    "WB_TOKEN_STATISTICS",
    "WB_TOKEN_ANALYTICS",
    "OZON_CLIENT_ID",
    "OZON_API_KEY",
    "ADMIN_API_KEY",
]

PLACEHOLDER_VALUES = {"", "...", "change_me"}


def main() -> int:
    missing: list[str] = []
    for key in REQUIRED:
        value = os.getenv(key, "")
        if value.strip() in PLACEHOLDER_VALUES:
            missing.append(key)

    if missing:
        print("Missing or placeholder values:")
        for key in missing:
            print(f"- {key}")
        return 1

    print("All required tokens look configured.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

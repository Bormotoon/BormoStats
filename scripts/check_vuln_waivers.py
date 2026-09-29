#!/usr/bin/env python3
"""Fail when a vulnerability waiver has expired or lacks mandatory fields.

Prints ``--ignore-vuln`` arguments for pip-audit with ``--pip-audit-args``.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path
from typing import Any

import yaml

ROOT_DIR = Path(__file__).resolve().parents[1]
WAIVERS_FILE = ROOT_DIR / "security" / "vulnerability-waivers.yml"
GRYPE_FILE = ROOT_DIR / ".grype.yaml"
REQUIRED_FIELDS = ("id", "reason", "owner", "expires")


def load_waivers(path: Path = WAIVERS_FILE) -> dict[str, list[dict[str, Any]]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {key: list(value or []) for key, value in data.items()}


def validate(waivers: dict[str, list[dict[str, Any]]], today: date) -> list[str]:
    problems: list[str] = []
    for ecosystem, entries in waivers.items():
        for entry in entries:
            missing = [name for name in REQUIRED_FIELDS if not entry.get(name)]
            if missing:
                problems.append(f"{ecosystem}:{entry.get('id', '?')}: missing {missing}")
                continue
            expires = entry["expires"]
            if not isinstance(expires, date):
                expires = date.fromisoformat(str(expires))
            if expires < today:
                problems.append(f"{ecosystem}:{entry['id']}: waiver expired on {expires}")
    grype_ids = {str(item.get("vulnerability")) for item in _grype_ignores()}
    waived = {str(entry.get("id")) for entry in waivers.get("grype", [])}
    for vuln in sorted(grype_ids - waived):
        problems.append(f".grype.yaml ignores {vuln} without an entry in {WAIVERS_FILE.name}")
    return problems


def _grype_ignores() -> list[dict[str, Any]]:
    if not GRYPE_FILE.is_file():
        return []
    data = yaml.safe_load(GRYPE_FILE.read_text(encoding="utf-8")) or {}
    return list(data.get("ignore") or [])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pip-audit-args", action="store_true")
    args = parser.parse_args()
    waivers = load_waivers()
    if args.pip_audit_args:
        print(" ".join(f"--ignore-vuln {entry['id']}" for entry in waivers.get("python", [])))
        return 0
    problems = validate(waivers, date.today())
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        return 1
    print("vulnerability waivers OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

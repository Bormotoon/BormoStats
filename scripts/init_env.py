#!/usr/bin/env python3
"""Create `.env` from an environment template and fill generated secrets.

Usage: ``python scripts/init_env.py --env dev`` (or ``make init ENV=dev``).
Secrets that are still placeholders in the template are replaced with random
values; marketplace credentials are left for the operator to fill in.
"""

from __future__ import annotations

import argparse
import secrets
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.env_validation import collect_bootstrap_issues, is_placeholder  # noqa: E402

ENVIRONMENTS = ("dev", "stage", "prod")
GENERATED_SECRETS = (
    "BOOTSTRAP_CH_ADMIN_PASSWORD",
    "CH_PASSWORD",
    "ADMIN_API_KEY",
    "REDIS_PASSWORD",
    "WEBHOOK_SECRET_KEY",
    "METRICS_BEARER_TOKEN",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", choices=ENVIRONMENTS, default="dev")
    parser.add_argument("--output", type=Path, default=ROOT_DIR / ".env")
    parser.add_argument("--force", action="store_true", help="overwrite an existing output file")
    return parser.parse_args()


def parse_env(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def render_env(template: str) -> tuple[str, list[str]]:
    """Return the template with generated secrets and the list of filled keys."""
    lines: list[str] = []
    generated: list[str] = []
    seen: set[str] = set()
    for raw_line in template.splitlines():
        key, sep, value = raw_line.partition("=")
        key = key.strip()
        if sep and key in GENERATED_SECRETS and not raw_line.lstrip().startswith("#"):
            seen.add(key)
            if is_placeholder(value):
                lines.append(f"{key}={secrets.token_urlsafe(32)}")
                generated.append(key)
                continue
        lines.append(raw_line)
    for key in GENERATED_SECRETS:
        if key not in seen:
            lines.append(f"{key}={secrets.token_urlsafe(32)}")
            generated.append(key)
    return "\n".join(lines) + "\n", generated


def main() -> int:
    args = parse_args()
    template_path = ROOT_DIR / f".env.{args.env}.example"
    if not template_path.is_file():
        print(f"Template not found: {template_path}", file=sys.stderr)
        return 1

    output: Path = args.output
    if output.exists() and not args.force:
        print(f"{output} already exists; pass --force to regenerate it.")
    else:
        rendered, generated = render_env(template_path.read_text(encoding="utf-8"))
        output.write_text(rendered, encoding="utf-8")
        output.chmod(0o600)
        print(f"Created {output} from {template_path.name}")
        if generated:
            print(f"Generated secrets: {', '.join(generated)}")

    issues = collect_bootstrap_issues(parse_env(output.read_text(encoding="utf-8")))
    if issues:
        print("\nFill in the remaining values before `make bootstrap`/`make up`:")
        for issue in issues:
            print(f"  - {issue}")
        return 2
    print("Environment file is complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Runtime configuration validation helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

PLACEHOLDER_VALUES = frozenset(
    {
        "...",
        "change_me",
        "replace_me",
        "replace-me",
        "replace-with-long-random-admin-key",
        "replace-with-real-ozon-api-key",
        "replace-with-real-ozon-client-id",
        "replace-with-real-wb-analytics-token",
        "replace-with-real-wb-statistics-token",
        "replace-with-strong-clickhouse-password",
        "replace-with-strong-bootstrap-clickhouse-password",
        "replace-with-strong-readonly-password",
        "replace-with-strong-value",
    }
)
INSECURE_CLICKHOUSE_USERS = frozenset({"admin", "default"})
REQUIRED_MARKETPLACE_KEYS = (
    "WB_TOKEN_STATISTICS",
    "WB_TOKEN_ANALYTICS",
    "OZON_CLIENT_ID",
    "OZON_API_KEY",
)


class InvalidConfigurationError(RuntimeError):
    """Raised when required runtime configuration is missing or unsafe."""


def _normalized(value: str | None) -> str:
    return (value or "").strip()


def is_placeholder(value: str | None) -> bool:
    normalized = _normalized(value)
    return not normalized or normalized.casefold() in PLACEHOLDER_VALUES


def _collect_clickhouse_runtime_issues(env: Mapping[str, str | None]) -> list[str]:
    issues: list[str] = []

    ch_user = _normalized(env.get("CH_USER"))
    if is_placeholder(ch_user):
        issues.append("CH_USER is required and cannot be blank or a placeholder")
    elif ch_user.casefold() in INSECURE_CLICKHOUSE_USERS:
        issues.append("CH_USER must be a dedicated application user, not 'default' or 'admin'")

    if is_placeholder(env.get("CH_PASSWORD")):
        issues.append("CH_PASSWORD must be set to a strong non-placeholder value")

    ch_ro_user = _normalized(env.get("CH_RO_USER"))
    ch_ro_password = _normalized(env.get("CH_RO_PASSWORD"))
    if ch_ro_user or ch_ro_password:
        if is_placeholder(ch_ro_user):
            issues.append(
                "CH_RO_USER must be set when a read-only ClickHouse password is configured"
            )
        if is_placeholder(ch_ro_password):
            issues.append("CH_RO_PASSWORD must be set to a strong non-placeholder value")

    return issues


def collect_backend_startup_issues(env: Mapping[str, str | None]) -> list[str]:
    issues = _collect_clickhouse_runtime_issues(env)

    if is_placeholder(env.get("ADMIN_API_KEY")):
        issues.append("ADMIN_API_KEY must be set to a strong non-placeholder value")

    return issues


def collect_worker_startup_issues(env: Mapping[str, str | None]) -> list[str]:
    issues = _collect_clickhouse_runtime_issues(env)

    for key in REQUIRED_MARKETPLACE_KEYS:
        if is_placeholder(env.get(key)):
            issues.append(
                f"{key} must be set to a real marketplace credential before worker startup"
            )

    return issues


def collect_bootstrap_issues(env: Mapping[str, str | None]) -> list[str]:
    issues = _collect_clickhouse_runtime_issues(env)
    bootstrap_user = _normalized(env.get("BOOTSTRAP_CH_ADMIN_USER"))
    if is_placeholder(bootstrap_user):
        issues.append("BOOTSTRAP_CH_ADMIN_USER must be set before bootstrap")
    elif bootstrap_user.casefold() in INSECURE_CLICKHOUSE_USERS:
        issues.append(
            "BOOTSTRAP_CH_ADMIN_USER must be a dedicated bootstrap user, not 'default' or 'admin'"
        )

    if is_placeholder(env.get("BOOTSTRAP_CH_ADMIN_PASSWORD")):
        issues.append("BOOTSTRAP_CH_ADMIN_PASSWORD must be set before bootstrap")

    if is_placeholder(env.get("ADMIN_API_KEY")):
        issues.append("ADMIN_API_KEY must be set before bootstrap")

    for key in REQUIRED_MARKETPLACE_KEYS:
        if is_placeholder(env.get(key)):
            issues.append(f"{key} must be set before bootstrap")

    return issues


def raise_for_issues(context: str, issues: Sequence[str]) -> None:
    if not issues:
        return

    details = "\n".join(f"- {issue}" for issue in issues)
    raise InvalidConfigurationError(f"Unsafe {context} configuration:\n{details}")

"""Application settings."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from common.env_validation import (
    STRICT_ENVIRONMENTS,
    collect_backend_startup_issues,
    raise_for_issues,
)
from common.file_secrets import load_file_secrets
from common.redis_url import build_redis_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = Field(default="dev", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    tz: str = Field(default="Europe/Warsaw", alias="TZ")

    ch_host: str = Field(default="localhost", alias="CH_HOST")
    ch_port: int = Field(default=8123, alias="CH_PORT")
    ch_user: str = Field(default="default", alias="CH_USER")
    ch_password: str = Field(default="", alias="CH_PASSWORD")
    ch_db: str = Field(default="mp_analytics", alias="CH_DB")
    ch_pool_maxsize: int = Field(default=16, alias="CH_POOL_MAXSIZE")
    ch_connect_timeout_seconds: int = Field(default=5, alias="CH_CONNECT_TIMEOUT_SECONDS")
    ch_query_timeout_seconds: int = Field(default=30, alias="CH_QUERY_TIMEOUT_SECONDS")

    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    redis_username: str = Field(default="", alias="REDIS_USERNAME")
    redis_password: str = Field(default="", alias="REDIS_PASSWORD")
    admin_api_key: str = Field(default="", alias="ADMIN_API_KEY")
    admin_allowed_networks: str = Field(
        default="",
        alias="ADMIN_ALLOWED_NETWORKS",
        description="Comma-separated CIDRs allowed to use the master admin key; empty = any",
    )
    public_read_api: bool = Field(
        default=False,
        alias="PUBLIC_READ_API",
        description="Legacy mode: allow anonymous reads of default-org analytics (dev only)",
    )
    auth_cache_ttl_seconds: int = Field(default=30, alias="AUTH_CACHE_TTL_SECONDS")
    metrics_bearer_token: str = Field(default="", alias="METRICS_BEARER_TOKEN")
    metrics_refresh_seconds: int = Field(default=30, alias="METRICS_REFRESH_SECONDS")
    readiness_cache_seconds: float = Field(default=5.0, alias="READINESS_CACHE_SECONDS")
    webhook_secret_key: str = Field(default="", alias="WEBHOOK_SECRET_KEY")
    webhook_allow_private_targets: bool = Field(
        default=False,
        alias="WEBHOOK_ALLOW_PRIVATE_TARGETS",
        description="Allow webhook URLs resolving to private/loopback IPs (dev only)",
    )
    openapi_enabled: bool = Field(default=True, alias="OPENAPI_ENABLED")

    ai_api_url: str = Field(default="", alias="AI_API_URL")
    ai_api_key: str = Field(default="", alias="AI_API_KEY")
    ai_model: str = Field(default="gpt-4o-mini", alias="AI_MODEL")

    wb_statistics_token: str = Field(default="", alias="WB_TOKEN_STATISTICS")
    wb_analytics_token: str = Field(default="", alias="WB_TOKEN_ANALYTICS")
    wb_marketplace_token: str = Field(default="", alias="WB_TOKEN_MARKETPLACE")
    ozon_client_id: str = Field(default="", alias="OZON_CLIENT_ID")
    ozon_api_key: str = Field(default="", alias="OZON_API_KEY")

    rate_limit_per_minute: str = Field(default="100/minute", alias="RATE_LIMIT_PER_MINUTE")
    admin_rate_limit_per_minute: str = Field(
        default="20/minute", alias="ADMIN_RATE_LIMIT_PER_MINUTE"
    )

    @property
    def is_strict_env(self) -> bool:
        return self.app_env.strip().casefold() in STRICT_ENVIRONMENTS

    @property
    def authenticated_redis_url(self) -> str:
        return build_redis_url(self.redis_url, self.redis_password, self.redis_username)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    load_file_secrets()
    settings = Settings()
    raise_for_issues(
        "backend startup",
        collect_backend_startup_issues(
            {
                "APP_ENV": settings.app_env,
                "ADMIN_API_KEY": settings.admin_api_key,
                "CH_USER": settings.ch_user,
                "CH_PASSWORD": settings.ch_password,
                "REDIS_PASSWORD": settings.redis_password,
                "WEBHOOK_SECRET_KEY": settings.webhook_secret_key,
                "PUBLIC_READ_API": "1" if settings.public_read_api else "",
                "WEBHOOK_ALLOW_PRIVATE_TARGETS": (
                    "1" if settings.webhook_allow_private_targets else ""
                ),
            }
        ),
    )
    return settings

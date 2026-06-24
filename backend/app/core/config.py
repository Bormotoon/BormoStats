"""Application settings."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from common.env_validation import collect_backend_startup_issues, raise_for_issues


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

    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    redis_password: str = Field(default="", alias="REDIS_PASSWORD")
    admin_api_key: str = Field(default="", alias="ADMIN_API_KEY")

    ai_api_url: str = Field(default="", alias="AI_API_URL")
    ai_api_key: str = Field(default="", alias="AI_API_KEY")
    ai_model: str = Field(default="gpt-4o-mini", alias="AI_MODEL")

    wb_statistics_token: str = Field(default="", alias="WB_TOKEN_STATISTICS")
    wb_analytics_token: str = Field(default="", alias="WB_TOKEN_ANALYTICS")
    ozon_client_id: str = Field(default="", alias="OZON_CLIENT_ID")
    ozon_api_key: str = Field(default="", alias="OZON_API_KEY")

    rate_limit_per_minute: str = Field(default="100/minute", alias="RATE_LIMIT_PER_MINUTE")
    admin_rate_limit_per_minute: str = Field(
        default="20/minute", alias="ADMIN_RATE_LIMIT_PER_MINUTE"
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    raise_for_issues(
        "backend startup",
        collect_backend_startup_issues(
            {
                "ADMIN_API_KEY": settings.admin_api_key,
                "CH_USER": settings.ch_user,
                "CH_PASSWORD": settings.ch_password,
            }
        ),
    )
    return settings

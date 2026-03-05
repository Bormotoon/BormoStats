"""Application settings."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    admin_api_key: str = Field(default="change_me", alias="ADMIN_API_KEY")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "telegram-community-logger"
    environment: str = "local"
    log_level: str = "INFO"

    telegram_bot_token: str = Field(..., min_length=10)
    telegram_webhook_secret_token: str = Field(..., min_length=16)
    telegram_bot_user_id: int | None = None
    telegram_channel_chat_id: int | None = None
    telegram_discussion_group_chat_id: int | None = None
    telegram_support_admin_user_ids: list[int] = Field(default_factory=list)
    telegram_accept_unmapped_discussion_threads: bool = False

    sqlite_path: Path = Path("data/app.db")

    google_credentials_path: Path | None = None
    google_credentials_json: str | None = None
    google_spreadsheet_id: str = Field(..., min_length=10)
    google_messages_sheet_name: str = "Messages"
    google_append_range: str = "Messages!A:W"
    google_request_timeout_seconds: int = 30

    sync_batch_size: int = 50
    sync_on_ingest: bool = True

    @field_validator("google_credentials_json", mode="before")
    @classmethod
    def empty_credentials_json_to_none(cls, value: object) -> object:
        if value == "":
            return None
        return value

    @field_validator("telegram_support_admin_user_ids", mode="before")
    @classmethod
    def parse_admin_ids(cls, value: object) -> list[int]:
        if value in (None, ""):
            return []
        if isinstance(value, list):
            return [int(item) for item in value]
        if isinstance(value, str):
            return [int(item.strip()) for item in value.split(",") if item.strip()]
        raise TypeError("telegram_support_admin_user_ids must be a comma-separated string or list")


@lru_cache
def get_settings() -> Settings:
    return Settings()

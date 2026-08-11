from functools import lru_cache
from typing import Annotated
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo

from pydantic import Field, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

APP_TIMEZONE = ZoneInfo("Europe/Moscow")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    postgres_host: str = "localhost"
    postgres_port: int = 15432
    postgres_user: str = "antonio"
    postgres_password: str = "antonio"
    postgres_db: str = "antonio"

    max_bot_token: str = ""
    max_webhook_secret: str = ""
    telegram_enabled: bool = False
    telegram_bot_token: str = ""
    admin_telegram_ids: Annotated[list[int], NoDecode] = Field(default_factory=list)
    admin_max_ids: Annotated[list[int], NoDecode] = Field(default_factory=list)
    trainers_max_chat_id: int | None = None
    webhook_host: str = "0.0.0.0"
    webhook_port: int = 8080
    webhook_base_url: str = ""
    fine_amount: int = 1000
    report_phrase: str = "Сегодня тренировка"
    max_api_base_url: str = "https://platform-api2.max.ru"
    max_ssl_verify: bool = True
    salary_trial_rate: int = 50
    salary_outreach_rate: int = 100
    error_notify_enabled: bool = True
    error_notify_telegram_ids: Annotated[list[int], NoDecode] = Field(default_factory=list)

    @field_validator("trainers_max_chat_id", mode="before")
    @classmethod
    def parse_optional_int(cls, value: object) -> int | None:
        if value is None or value == "":
            return None
        return int(value)

    @field_validator("max_ssl_verify", "telegram_enabled", mode="before")
    @classmethod
    def parse_bool(cls, value: object, info: ValidationInfo) -> bool:
        defaults = {
            "max_ssl_verify": True,
            "telegram_enabled": False,
        }
        if isinstance(value, bool):
            return value
        if value is None or value == "":
            return defaults.get(info.field_name, False)
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    @field_validator(
        "admin_telegram_ids",
        "admin_max_ids",
        "error_notify_telegram_ids",
        mode="before",
    )
    @classmethod
    def parse_id_list(cls, value: object) -> list[int]:
        if value is None or value == "":
            return []
        if isinstance(value, int):
            return [value]
        if isinstance(value, list):
            return [int(item) for item in value]
        if isinstance(value, str):
            normalized = value.replace(";", ",").replace("\n", ",").replace(" ", ",")
            return [int(item.strip()) for item in normalized.split(",") if item.strip()]
        raise ValueError("ID list must contain integers")

    @property
    def database_url(self) -> str:
        password = quote_plus(self.postgres_password)
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def admin_ids(self) -> set[int]:
        return set(self.admin_telegram_ids)

    @property
    def admin_max_id_set(self) -> set[int]:
        return set(self.admin_max_ids)

    @property
    def is_telegram_enabled(self) -> bool:
        return self.telegram_enabled and bool(self.telegram_bot_token)


@lru_cache
def get_settings() -> Settings:
    return Settings()

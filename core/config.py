import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_database_url() -> str:
    if os.path.exists("/.dockerenv"):
        return "postgresql://postgres:postgres@supabase_db_app:5432/postgres"
    return "postgresql://postgres:postgres@localhost:54322/postgres"


class Settings(BaseSettings):
    WHATSAPP_PROVIDER: str = "meta"
    WHATSAPP_PHONE_NUMBER_ID: str = ""
    WHATSAPP_ACCESS_TOKEN: str = ""
    WHATSAPP_VERIFY_TOKEN: str = ""
    META_APP_SECRET: str = ""
    META_APP_ID: str = ""
    WHATSAPP_BUSINESS_ACCOUNT_ID: str = ""

    LLM_PROVIDER: str = "nvidia"
    LLM_MODEL: str = "meta/llama-3.3-70b-instruct"
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = "https://integrate.api.nvidia.com/v1"

    DATABASE_URL: str = _default_database_url()
    DB_POOL_MIN: int = 2
    DB_POOL_MAX: int = 10

    META_API_URL: str = "https://graph.facebook.com/v25.0"

    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8080

    DASHBOARD_TOKEN: str = ""
    DASHBOARD_AUTH_SECRET: str = ""
    CORS_ORIGINS: str = "*"
    SKIP_STARTUP_VALIDATION: bool = False
    SKIP_WEBHOOK_SIGNATURE: bool = False

    TOOL_MAX_ITERATIONS: int = 5
    TOOL_EXECUTION_TTL: int = 300
    MARK_READ_DELAY_MS: int = 200

    FOLLOW_UP_DELAY_MINUTES: int = 30
    RE_ENGAGEMENT_DAYS: int = 7
    SCHEDULER_POLL_INTERVAL: int = 60

    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parents[1] / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()

from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    WHATSAPP_PROVIDER: str = "meta"
    WHATSAPP_PHONE_NUMBER_ID: str = ""
    WHATSAPP_ACCESS_TOKEN: str = ""
    WHATSAPP_VERIFY_TOKEN: str = ""

    LLM_PROVIDER: str = "nvidia"
    LLM_MODEL: str = "meta/llama-3.1-70b-instruct"
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = "https://integrate.api.nvidia.com/v1"

    DB_DIR: str = "/tmp/hermes"
    DB_NAME: str = "whatsapp_conversations.db"
    DB_PATH: str = ""

    META_API_URL: str = "https://graph.facebook.com/v25.0"

    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8080

    DASHBOARD_TOKEN: str = ""
    CORS_ORIGINS: str = "*"

    class Config:
        env_file = str(Path(__file__).resolve().parents[1] / ".env")
        env_file_encoding = "utf-8"
        extra = "ignore"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.DB_PATH:
            import os
            self.DB_PATH = os.path.join(self.DB_DIR, self.DB_NAME)


settings = Settings()

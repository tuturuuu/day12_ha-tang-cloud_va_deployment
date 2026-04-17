from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    APP_NAME: str = "my-production-agent"
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    REDIS_URL: str = "redis://default:KHxMbkflnnYChQapyQHvitCuuJyqogKx@nozomi.proxy.rlwy.net:18951"
    AGENT_API_KEY: str = "change-me-in-production"
    LOG_LEVEL: str = "INFO"

    RATE_LIMIT_PER_MINUTE: int = 10
    RATE_LIMIT_WINDOW_SECONDS: int = 60
    MONTHLY_BUDGET_USD: float = 10.0
    HISTORY_MAX_MESSAGES: int = Field(default=20, ge=2, le=200)

    COST_PER_1K_INPUT_TOKENS: float = 0.0010
    COST_PER_1K_OUTPUT_TOKENS: float = 0.0020

settings = Settings()

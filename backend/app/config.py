"""Application configuration loaded from environment variables.

Secrets (API keys) are only ever read here, on the server. They are never
returned by any endpoint, logged, or stored in the database.
"""
from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://satyasetu:satyasetu@db:5432/satyasetu"
    data_dir: str = "/data"
    log_level: str = "INFO"
    cookie_secure: bool = False

    # --- LLM provider (Gemini API) ---
    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-3.8-flash"
    # Used only if the primary model is unavailable to this key or its daily quota is exhausted.
    gemini_fallback_model: str = "gemini-3.5-flash-lite"
    gemini_timeout_s: float = 60.0
    gemini_max_requests_per_minute: int = 8
    gemini_max_requests_per_day: int = 200

    # --- Search provider (Tavily) ---
    tavily_api_key: SecretStr | None = None
    tavily_max_searches_per_day: int = 40
    tavily_max_searches_per_month: int = 900
    tavily_timeout_s: float = 20.0

    # --- Optional: Google Fact Check Tools API (free, needs a Google Cloud API key) ---
    factcheck_api_key: SecretStr | None = None

    # --- Per-check budgets ---
    max_input_chars: int = 6000
    max_claims_per_check: int = 4
    max_searches_per_claim: int = 2
    max_sources_per_claim: int = 4
    max_total_searches_per_check: int = 6
    check_timeout_s: float = 180.0
    fetch_timeout_s: float = 10.0
    fetch_max_bytes: int = 3_000_000
    max_concurrent_checks: int = 3
    verifications_per_minute_per_session: int = 6

    # --- Uploads and media ---
    max_upload_bytes: int = 15_000_000
    max_audio_seconds: int = 300
    whisper_enabled: bool = True
    whisper_model: str = "base"

    # --- Retention ---
    retention_days: int = 30

    @property
    def gemini_configured(self) -> bool:
        return bool(self.gemini_api_key and self.gemini_api_key.get_secret_value().strip())

    @property
    def tavily_configured(self) -> bool:
        return bool(self.tavily_api_key and self.tavily_api_key.get_secret_value().strip())

    @property
    def factcheck_configured(self) -> bool:
        return bool(self.factcheck_api_key and self.factcheck_api_key.get_secret_value().strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()


ALLOWED_LANGUAGES = ("en", "hi", "mr")
LANGUAGE_NAMES = {"en": "English", "hi": "Hindi", "mr": "Marathi"}

"""
config.py
---------
Centralised configuration using pydantic-settings.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── LLM ──────────────────────────────────────────────────────────────────
    GROQ_API_KEY: str
    GEMINI_API_KEY: str | None = None

    # Groq model names
    SMART_MODEL: str = "llama-3.3-70b-versatile"   # entailment, reasoning
    FAST_MODEL: str = "llama-3.1-8b-instant"        # bulk extraction

    # ── App ───────────────────────────────────────────────────────────────────
    APP_ENV: str = "development"
    LOG_LEVEL: str = "INFO"

    # ── Database ──────────────────────────────────────────────────────────────
    DATABASE_URL: str = "sqlite+aiosqlite:///./tender_compliance.db"

    # ── Vector store ──────────────────────────────────────────────────────────
    CHROMA_PERSIST_DIR: str = "./chroma_db"

    # ── Model cache ───────────────────────────────────────────────────────────
    HF_HOME: str = "./model_cache"

    # ── Processing ────────────────────────────────────────────────────────────
    BATCH_SIZE: int = 10
    MAX_RETRIES: int = 3
    RATE_LIMIT_SLEEP: float = 0.5

    # ── TenderAI chat ─────────────────────────────────────────────────────────
    CHAT_LLM_TEMPERATURE: float = 0.0
    CHAT_MAX_TOKENS: int = 800

    # ── Retrieval ─────────────────────────────────────────────────────────────
    TOP_K_RETRIEVAL: int = 20
    TOP_K_RERANK: int = 5
    PROBABILITY_NONE_THRESHOLD: float = 0.05

    # ── Upload ────────────────────────────────────────────────────────────────
    UPLOAD_DIR: str = "./uploads"
    MAX_FILE_SIZE_MB: int = 50


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
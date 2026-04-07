"""
Application configuration — loaded from environment variables.
All secrets and environment-specific values must come from .env or the
container environment.  NEVER hardcode credentials, project IDs, or
service URLs here.

Fields WITHOUT a default will raise a descriptive ValidationError at
startup if the corresponding env-var is missing, which is intentional —
fail fast, fail loud.
"""

from functools import lru_cache
from pathlib import Path
from typing import List, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

# Locate the .env file: walk up from this file until we find it or give up.
_here = Path(__file__).resolve()
_env_file: Path | str = ".env"
for _candidate in [
    _here.parents[3] / ".env",  # project root  (core→app→backend→root)
    _here.parents[2] / ".env",  # backend root
]:
    if _candidate.is_file():
        _env_file = _candidate
        break


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_env_file),
        case_sensitive=True,
        extra="ignore",
    )

    # ── App ────────────────────────────────────────────────────────────────
    APP_ENV: str = "development"          # safe default (non-secret)
    SECRET_KEY: str                        # REQUIRED — no default
    ALGORITHM: str = "HS256"              # safe default (well-known constant)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    CORS_ORIGINS: List[str] = ["http://localhost:3000"]

    # ── Database ───────────────────────────────────────────────────────────
    DATABASE_URL: str                      # REQUIRED — built from creds or supplied directly
    POSTGRES_HOST: str                     # REQUIRED
    POSTGRES_PORT: int = 5432             # safe default (standard port)
    POSTGRES_DB: str                       # REQUIRED
    POSTGRES_USER: str                     # REQUIRED
    POSTGRES_PASSWORD: str                 # REQUIRED

    # ── Redis / Celery ─────────────────────────────────────────────────────
    REDIS_URL: str                         # REQUIRED
    CELERY_BROKER_URL: str                 # REQUIRED
    CELERY_RESULT_BACKEND: str             # REQUIRED
    CACHE_TTL_SECONDS: int = 3600         # safe default (tuning knob)

    # ── GCP ────────────────────────────────────────────────────────────────
    GCP_PROJECT_ID: str                    # REQUIRED
    GCP_LOCATION: str                      # REQUIRED
    GOOGLE_APPLICATION_CREDENTIALS: str    # REQUIRED (path to service-account JSON)

    # ── GCS (Object Storage) ───────────────────────────────────────────────
    GCS_BUCKET_NAME: str                   # REQUIRED

    # ── Gemini Models ──────────────────────────────────────────────────────
    GEMINI_LARGE_MODEL: str                # REQUIRED (model names change — pin via env)
    GEMINI_SMALL_MODEL: str                # REQUIRED
    EMBEDDING_MODEL: str                   # REQUIRED
    EMBEDDING_DIMS: int                    # REQUIRED (must match the model)
    MAX_TOKENS_RESPONSE: int = 2048       # safe default (tuning knob)

    # ── Rate Limiting ──────────────────────────────────────────────────────
    RATE_LIMIT_AUTH: int = 60             # safe default (tuning knob)
    RATE_LIMIT_ANON: int = 10             # safe default (tuning knob)

    # ── RAG ────────────────────────────────────────────────────────────────
    CHUNK_SIZE: int = 512                 # safe default (tuning knob)
    CHUNK_OVERLAP: int = 64              # safe default (tuning knob)
    TOP_K_RETRIEVAL: int = 8             # safe default (tuning knob)
    SIMILARITY_THRESHOLD: float = 0.65   # safe default (tuning knob)
    MMR_LAMBDA: float = 0.5              # safe default (tuning knob)
    EMBED_BATCH_SIZE: int = 50           # safe default (tuning knob)

    # ── Session ────────────────────────────────────────────────────────────
    ANON_SESSION_TTL_HOURS: int = 24     # safe default (tuning knob)
    SHORT_TERM_MEMORY_MESSAGES: int = 10  # safe default (tuning knob)
    SUMMARY_TRIGGER_MESSAGES: int = 20   # safe default (tuning knob)


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

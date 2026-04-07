"""
RAG Application - Main Entry Point
Production-grade FastAPI application with full RAG pipeline.
"""

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# Ensure the backend directory is on sys.path so `app` package is importable
_backend_dir = str(Path(__file__).resolve().parent.parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

# Load .env from the project root (one level above backend/)
_project_root = str(Path(__file__).resolve().parent.parent.parent)
_env_path = os.path.join(_project_root, ".env")
if os.path.isfile(_env_path):
    from dotenv import load_dotenv
    load_dotenv(_env_path, override=True)

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.core.rate_limiter import limiter
from app.db.session import engine, Base
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    configure_logging()
    logger.info("Starting RAG Application", env=settings.APP_ENV)

    # Verify DB + pgvector extension (schema managed by Alembic migrations)
    from sqlalchemy import text
    async with engine.begin() as conn:
        await conn.execute(text("SELECT 1"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

    logger.info("Database connection verified")
    yield

    logger.info("Shutting down RAG Application")
    await engine.dispose()


def create_application() -> FastAPI:
    app = FastAPI(
        title="RAG Application API",
        description="Production-grade Retrieval-Augmented Generation system",
        version="1.0.0",
        docs_url="/docs" if settings.APP_ENV != "production" else None,
        redoc_url="/redoc" if settings.APP_ENV != "production" else None,
        lifespan=lifespan,
    )

    # ── Middleware ─────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)

    # ── Routes ────────────────────────────────────────────
    app.include_router(api_router, prefix="/api/v1")

    # ── Exception Handlers ────────────────────────────────
    register_exception_handlers(app)

    # ── Metrics ───────────────────────────────────────────
    Instrumentator().instrument(app).expose(app)

    return app


app = create_application()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        debug=True,
        reload=settings.APP_ENV == "development",
    )

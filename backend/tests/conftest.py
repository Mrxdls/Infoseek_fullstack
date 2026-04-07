"""
Shared test fixtures for the RAG application backend.
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.main import app
from app.db.session import Base, get_db
from app.core.rate_limiter import limiter

# ─── Test Database Setup ──────────────────────────────────────────────────────

TEST_DB_URL = "sqlite+aiosqlite:///./test.db"

test_engine = create_async_engine(TEST_DB_URL, echo=False)
TestSession = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_db():
    # Disable rate limiting for tests
    limiter.enabled = False
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db_session():
    """Provides a clean DB session per test."""
    async with TestSession() as session:
        yield session


@pytest_asyncio.fixture
async def client(db_session: AsyncSession):
    """HTTP test client that shares the same DB session."""
    async def override_get_db():
        try:
            yield db_session
            await db_session.commit()
        except Exception:
            await db_session.rollback()
            raise

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.pop(get_db, None)


@pytest_asyncio.fixture
async def auth_headers(client: AsyncClient) -> dict:
    """Register + login a test user, return auth headers."""
    await client.post("/api/v1/auth/register", json={
        "email": "authuser@test.com",
        "password": "testpass123",
        "full_name": "Auth User",
    })
    resp = await client.post("/api/v1/auth/login", json={
        "email": "authuser@test.com",
        "password": "testpass123",
    })
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def admin_headers(client: AsyncClient, db_session: AsyncSession) -> dict:
    """Register + promote to admin + login, return auth headers."""
    from app.db.models.models import User, UserRole
    from sqlalchemy import select

    await client.post("/api/v1/auth/register", json={
        "email": "admin@test.com",
        "password": "adminpass123",
        "full_name": "Admin User",
    })
    # Promote to admin directly in DB
    result = await db_session.execute(select(User).where(User.email == "admin@test.com"))
    user = result.scalar_one()
    user.role = UserRole.ADMIN
    await db_session.commit()

    resp = await client.post("/api/v1/auth/login", json={
        "email": "admin@test.com",
        "password": "adminpass123",
    })
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}

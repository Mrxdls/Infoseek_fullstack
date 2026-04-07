#!/usr/bin/env python3
"""
Seed script — creates a default admin user.
Run: docker compose exec api python scripts/seed_admin.py
"""

import asyncio
import os
import sys

sys.path.insert(0, "/app")

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.core.config import settings
from app.db.models.models import User, UserRole
from app.services.auth.auth_service import hash_password
from sqlalchemy import select


async def seed():
    engine = create_async_engine(settings.DATABASE_URL)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    admin_email = os.getenv("ADMIN_EMAIL", "admin@studyrag.com")
    admin_password = os.getenv("ADMIN_PASSWORD", "Admin@1234!")
    admin_name = os.getenv("ADMIN_NAME", "System Admin")

    async with SessionLocal() as db:
        result = await db.execute(select(User).where(User.email == admin_email))
        existing = result.scalar_one_or_none()

        if existing:
            print(f"[seed] Admin already exists: {admin_email}")
            return

        admin = User(
            email=admin_email,
            hashed_password=hash_password(admin_password),
            full_name=admin_name,
            role=UserRole.ADMIN,
            is_active=True,
            is_verified=True,
        )
        db.add(admin)
        await db.commit()
        print(f"[seed] ✓ Admin created: {admin_email}")
        print(f"[seed]   Password: {admin_password}")
        print(f"[seed]   CHANGE THIS PASSWORD IMMEDIATELY IN PRODUCTION.")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())

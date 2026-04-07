#!/usr/bin/env python3
"""
Create an initial admin user for the RAG application.
Usage: python scripts/create_admin.py
"""

import asyncio
import os
import sys
from pathlib import Path

# Ensure app package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Load .env
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env", override=True)

from sqlalchemy import select
from app.db.session import engine, AsyncSessionLocal, Base
from app.db.models.models import User, UserRole
from app.services.auth.auth_service import hash_password


ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "mriduls512@gmail.com")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123456")
ADMIN_NAME = os.getenv("ADMIN_NAME", "System Admin")


async def main():
    # Create tables if they don't exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        # Check if admin already exists
        result = await db.execute(select(User).where(User.email == ADMIN_EMAIL))
        existing = result.scalar_one_or_none()

        if existing:
            if existing.role != UserRole.ADMIN:
                existing.role = UserRole.ADMIN
                await db.commit()
                print(f"User {ADMIN_EMAIL} promoted to ADMIN.")
            else:
                print(f"Admin user {ADMIN_EMAIL} already exists.")
            return

        admin = User(
            email=ADMIN_EMAIL,
            hashed_password=hash_password(ADMIN_PASSWORD),
            full_name=ADMIN_NAME,
            role=UserRole.ADMIN,
            is_active=True,
        )
        db.add(admin)
        await db.commit()

        print(f"Admin user created successfully!")
        print(f"  Email:    {ADMIN_EMAIL}")
        print(f"  Password: {ADMIN_PASSWORD}")
        print(f"  Role:     admin")
        print()
        print("Change the password after first login or set ADMIN_PASSWORD env var before running.")


if __name__ == "__main__":
    asyncio.run(main())

"""
Authentication and authorization service.
Handles JWT creation/validation, password hashing, and RBAC.
"""

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID as PyUUID

import structlog
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
import bcrypt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models.models import RefreshToken, User, UserRole
from app.db.session import get_db

logger = structlog.get_logger()
security = HTTPBearer()


# ─── Password Utilities ───────────────────────────────────────────────────────


def _prehash(password: str) -> str:
    """SHA-256 pre-hash to bypass bcrypt's 72-byte limit."""
    import base64
    digest = hashlib.sha256(password.encode("utf-8")).digest()
    return base64.b64encode(digest).decode("ascii")


def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(_prehash(password).encode("ascii"), salt).decode("ascii")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_prehash(plain).encode("ascii"), hashed.encode("ascii"))
    except ValueError:
        return False


# ─── JWT Utilities ────────────────────────────────────────────────────────────


def _create_token(subject: str, expires_delta: timedelta, token_type: str) -> str:
    import uuid
    expire = datetime.now(timezone.utc) + expires_delta
    payload = {"sub": subject, "exp": expire, "type": token_type, "jti": uuid.uuid4().hex}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_access_token(user_id: str) -> str:
    return _create_token(
        user_id,
        timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        "access",
    )


def create_refresh_token(user_id: str) -> str:
    return _create_token(
        user_id,
        timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        "refresh",
    )


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e


# ─── Dependency: Current User ─────────────────────────────────────────────────


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    payload = decode_token(credentials.credentials)

    if payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Invalid token type")

    user_id = payload.get("sub")
    try:
        user_uuid = PyUUID(user_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=401, detail="Invalid token")
    result = await db.execute(select(User).where(User.id == user_uuid))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is blocked")

    return user


async def get_current_active_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role not in (UserRole.ADMIN, UserRole.STAFF):
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


async def get_current_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Super admin access required")
    return current_user


# ─── Auth Service ─────────────────────────────────────────────────────────────


class AuthService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def register_user(self, email: str, password: str, full_name: Optional[str] = None) -> User:
        result = await self.db.execute(select(User).where(User.email == email))
        if result.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Email already registered")

        user = User(
            email=email,
            hashed_password=hash_password(password),
            full_name=full_name,
        )
        self.db.add(user)
        await self.db.flush()
        logger.info("User registered", user_id=str(user.id), email=email)
        return user

    async def authenticate(self, email: str, password: str) -> User:
        result = await self.db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()

        if not user or not verify_password(password, user.hashed_password):
            raise HTTPException(status_code=401, detail="Invalid credentials")
        if not user.is_active:
            raise HTTPException(status_code=403, detail="Account is blocked")

        user.last_login = datetime.now(timezone.utc)
        return user

    async def store_refresh_token(self, user_id: PyUUID, raw_token: str) -> None:
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        expires_at = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
        rt = RefreshToken(user_id=user_id, token_hash=token_hash, expires_at=expires_at)
        self.db.add(rt)

    async def rotate_refresh_token(self, raw_token: str) -> tuple[User, str, str]:
        """Validate old refresh token, revoke it, issue new pair."""
        payload = decode_token(raw_token)
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Invalid token type")

        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        result = await self.db.execute(
            select(RefreshToken).where(
                RefreshToken.token_hash == token_hash,
                RefreshToken.revoked == False,
            )
        )
        rt = result.scalar_one_or_none()
        now = datetime.now(timezone.utc)
        if not rt or rt.expires_at.replace(tzinfo=timezone.utc) < now:
            raise HTTPException(status_code=401, detail="Refresh token invalid or expired")

        rt.revoked = True

        user_result = await self.db.execute(select(User).where(User.id == rt.user_id))
        user = user_result.scalar_one_or_none()
        if not user or not user.is_active:
            raise HTTPException(status_code=401, detail="User unavailable")

        new_access = create_access_token(str(user.id))
        new_refresh = create_refresh_token(str(user.id))
        await self.store_refresh_token(user.id, new_refresh)

        return user, new_access, new_refresh

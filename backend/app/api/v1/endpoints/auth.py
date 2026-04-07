"""
Authentication endpoints: register, login, refresh, logout.
"""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limiter import limiter, ANON_RATE
from app.db.session import get_db
from app.schemas.schemas import TokenRefresh, TokenResponse, UserCreate, UserLogin, UserResponse
from app.services.auth.auth_service import (
    AuthService,
    create_access_token,
    create_refresh_token,
    get_current_user,
)
from app.db.models.models import User

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=UserResponse, status_code=201)
@limiter.limit(ANON_RATE)
async def register(request: Request, body: UserCreate, db: AsyncSession = Depends(get_db)):
    svc = AuthService(db)
    user = await svc.register_user(body.email, body.password, body.full_name)
    return user


@router.post("/login", response_model=TokenResponse)
@limiter.limit(ANON_RATE)
async def login(request: Request, body: UserLogin, db: AsyncSession = Depends(get_db)):
    svc = AuthService(db)
    user = await svc.authenticate(body.email, body.password)
    access = create_access_token(str(user.id))
    refresh = create_refresh_token(str(user.id))
    await svc.store_refresh_token(user.id, refresh)
    return TokenResponse(access_token=access, refresh_token=refresh)


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit(ANON_RATE)
async def refresh_token(request: Request, body: TokenRefresh, db: AsyncSession = Depends(get_db)):
    svc = AuthService(db)
    _, new_access, new_refresh = await svc.rotate_refresh_token(body.refresh_token)
    return TokenResponse(access_token=new_access, refresh_token=new_refresh)


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    return current_user

"""
API v1 router — aggregates all endpoint routers.
"""

from fastapi import APIRouter

from app.api.v1.endpoints.auth import router as auth_router
from app.api.v1.endpoints.chat import router as chat_router
from app.api.v1.endpoints.documents import router as documents_router
from app.api.v1.endpoints.admin import router as admin_router

api_router = APIRouter()

api_router.include_router(auth_router)
api_router.include_router(documents_router)
api_router.include_router(chat_router)
api_router.include_router(admin_router)


@api_router.get("/health", tags=["Health"])
async def health_check():
    return {"status": "ok", "version": "1.0.0"}

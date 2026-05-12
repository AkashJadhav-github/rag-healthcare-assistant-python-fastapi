from fastapi import APIRouter

from .admin import router as admin_router
from .auth import router as auth_router
from .health import router as health_router
from .knowledge import router as knowledge_router

api_router = APIRouter()
api_router.include_router(auth_router, prefix="/auth", tags=["Authentication"])
api_router.include_router(knowledge_router, prefix="/knowledge", tags=["Knowledge"])
api_router.include_router(admin_router, prefix="/admin", tags=["Admin"])
api_router.include_router(health_router, prefix="/health", tags=["Health"])

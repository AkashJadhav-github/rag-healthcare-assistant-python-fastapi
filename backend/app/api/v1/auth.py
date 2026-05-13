from datetime import datetime, timezone
from typing import Any, Dict, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
)
from ...db.database import get_db
from ...models.audit import AuditAction, AuditLog
from ...models.user import User
from ...services.cache import cache_service
from ...services.metrics import auth_total
from ..deps import get_client_ip, get_current_active_user

logger = structlog.get_logger()
router = APIRouter()


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class LoginRequest(BaseModel):
    username: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class RefreshResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


@router.post("/login", response_model=TokenResponse)
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
    client_ip: str = Depends(get_client_ip),
):
    rate_key = f"rate:login:{client_ip}"
    attempts = await cache_service.increment(rate_key, expire=300)
    if attempts > 10:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts",
        )

    result = await db.execute(select(User).where(User.email == form_data.username))
    user = result.scalar_one_or_none()

    if not user or not verify_password(form_data.password, user.hashed_password):
        auth_total.labels(status="failed").inc()
        await _log_audit(
            db,
            None,
            AuditAction.LOGIN,
            client_ip,
            {"username": form_data.username, "success": False},
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect credentials")

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled")

    user.last_login = datetime.now(timezone.utc)
    await db.commit()

    access_token = create_access_token(subject=str(user.id))
    refresh_token = create_refresh_token(subject=str(user.id))

    auth_total.labels(status="success").inc()
    await _log_audit(db, user.id, AuditAction.LOGIN, client_ip, {"success": True})

    return TokenResponse(access_token=access_token, refresh_token=refresh_token, expires_in=1800)


@router.post("/refresh", response_model=RefreshResponse)
async def refresh_token(
    body: RefreshRequest,
    db: AsyncSession = Depends(get_db),
):
    payload = decode_token(body.refresh_token)

    if payload.get("type") != "refresh":
        logger.warning("refresh_token_wrong_type", token_type=payload.get("type"))
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")

    user_id = payload.get("sub")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user or not user.is_active:
        logger.warning("refresh_token_user_invalid", user_id=user_id, found=user is not None)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
        )

    access_token = create_access_token(subject=str(user.id))
    logger.info("token_refreshed", user_id=str(user.id))

    return RefreshResponse(access_token=access_token, expires_in=1800)


@router.post("/logout")
async def logout(
    current_user: User = Depends(get_current_active_user),
    client_ip: str = Depends(get_client_ip),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    await cache_service.delete(f"user:{current_user.id}")
    await _log_audit(db, current_user.id, AuditAction.LOGOUT, client_ip, {})
    return {"message": "Logged out successfully"}


@router.get("/me")
async def get_me(
    current_user: User = Depends(get_current_active_user),
) -> Dict[str, Any]:
    return {
        "id": str(current_user.id),
        "email": current_user.email,
        "username": current_user.username,
        "full_name": current_user.full_name,
        "role": current_user.role.value,
        "department": current_user.department,
    }


async def _log_audit(
    db: AsyncSession,
    user_id: Optional[Any],
    action: AuditAction,
    ip: str,
    details: Dict[str, Any],
) -> None:
    try:
        log = AuditLog(user_id=user_id, action=action, ip_address=ip, details=details)
        db.add(log)
        await db.commit()
    except Exception as e:
        logger.warning("audit_log_failed", error=str(e))

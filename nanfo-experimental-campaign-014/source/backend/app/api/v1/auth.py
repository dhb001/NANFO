"""NANFO Backend — Auth API router (/api/v1/auth/*).

Implements Authentication.md §3 endpoints with full API_STANDARD.md §2 envelope.
All endpoints validate JWT via dependencies except /login and /refresh.
"""

import time
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import (
    RequestMeta,
    TokenClaims,
    get_current_user,
    get_db,
    get_redis,
    get_request_meta,
)
from app.core.responses import APIResponse, success_response
from app.modules.identity.schemas import (
    LoginRequest,
    RefreshRequest,
    TokenPair,
    UserProfile,
)
from app.modules.identity.service import AuthService

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])


@router.post("/login", response_model=APIResponse[TokenPair], status_code=status.HTTP_200_OK)
async def login(
    req: LoginRequest,
    request: Request,
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[object, Depends(get_redis)],
):
    started = time.monotonic()
    ip = request.client.host if request.client else "unknown"
    svc = AuthService(db=db, redis=redis)
    result = await svc.login(
        email=req.email,
        password=req.password,
        ip_address=ip,
        correlation_id=meta.request_id,
    )
    return success_response(result, meta.request_id, started, meta.timestamp)


@router.post("/logout", response_model=APIResponse[dict], status_code=status.HTTP_200_OK)
async def logout(
    claims: Annotated[TokenClaims, Depends(get_current_user)],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[object, Depends(get_redis)],
):
    started = time.monotonic()
    svc = AuthService(db=db, redis=redis)
    await svc.logout(jti=claims.jti, exp=claims.exp, user_id=claims.user_id, correlation_id=meta.request_id, sid=claims.sid)
    return success_response({"logged_out": True}, meta.request_id, started, meta.timestamp)


@router.post("/refresh", response_model=APIResponse[TokenPair], status_code=status.HTTP_200_OK)
async def refresh(
    req: RefreshRequest,
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[object, Depends(get_redis)],
):
    started = time.monotonic()
    svc = AuthService(db=db, redis=redis)
    result = await svc.refresh(refresh_token=req.refresh_token, correlation_id=meta.request_id)
    return success_response(result, meta.request_id, started, meta.timestamp)


@router.get("/me", response_model=APIResponse[UserProfile], status_code=status.HTTP_200_OK)
async def me(
    claims: Annotated[TokenClaims, Depends(get_current_user)],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[object, Depends(get_redis)],
):
    started = time.monotonic()
    svc = AuthService(db=db, redis=redis)
    profile = await svc.get_profile(user_id=claims.user_id)
    return success_response(profile, meta.request_id, started, meta.timestamp)

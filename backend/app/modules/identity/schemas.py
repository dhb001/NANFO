"""NANFO Backend — Identity module Pydantic schemas.

Request/response schemas for auth endpoints (Authentication.md §3, §8).
hashed_password is NEVER included in any schema returned to clients.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr

# ── Request schemas ───────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


# ── Response schemas ──────────────────────────────────────────────────────────

class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


class AccessToken(BaseModel):
    access_token: str
    expires_in: int


class UserProfile(BaseModel):
    user_id: uuid.UUID
    email: str
    display_name: str | None
    roles: list[str]
    permissions: list[str]

    model_config = {"from_attributes": True}


class AuditLogEntry(BaseModel):
    log_id: uuid.UUID
    event_type: str
    actor_id: uuid.UUID | None
    resource_type: str | None
    resource_id: uuid.UUID | None
    org_id: uuid.UUID | None
    correlation_id: uuid.UUID
    timestamp: datetime
    metadata: dict | None = None

    model_config = {"from_attributes": True}

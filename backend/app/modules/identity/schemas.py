"""NANFO Backend — Identity module Pydantic schemas.

Request/response schemas for auth endpoints (Authentication.md §3, §8).
hashed_password is NEVER included in any schema returned to clients.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, EmailStr, StringConstraints

# RFC 5321 bound on a forward-path address; rejected before address parsing.
EMAIL_MAX_LENGTH = 254
# Issued refresh tokens are well under 1 KiB; anything larger is never a NANFO token.
REFRESH_TOKEN_MAX_LENGTH = 4096


def _bounded_email(value: object) -> object:
    if isinstance(value, str) and len(value) > EMAIL_MAX_LENGTH:
        raise ValueError("Email address is too long.")
    return value


BoundedEmail = Annotated[EmailStr, BeforeValidator(_bounded_email)]

AuditScope = Literal["org", "platform"]


# ── Request schemas ───────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: BoundedEmail
    # Deliberately unbounded here: >72-byte secrets must receive the generic 401
    # (ADR-028 C11), not a distinguishable 422. The request body limit caps size.
    password: str


class RefreshRequest(BaseModel):
    refresh_token: Annotated[str, StringConstraints(min_length=1, max_length=REFRESH_TOKEN_MAX_LENGTH)]


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


class AuditLogPage(BaseModel):
    items: list[AuditLogEntry]
    total: int
    page: int
    page_size: int
    scope: AuditScope = "org"

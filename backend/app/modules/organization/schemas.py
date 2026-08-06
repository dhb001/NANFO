"""NANFO Backend — Organization module Pydantic schemas.

Request/response schemas for organization, workspace, and membership endpoints.
All endpoints follow API_STANDARD.md §2 envelope via the responses module.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, field_validator
import re


def _validate_slug(value: str) -> str:
    """Normalize and validate org slug: lowercase, alphanumeric + hyphens only."""
    normalized = value.lower().strip()
    if not re.match(r'^[a-z0-9][a-z0-9\-]{0,61}[a-z0-9]$', normalized):
        raise ValueError("Slug must be 3-63 characters, lowercase alphanumeric and hyphens only, and must not start or end with a hyphen.")
    return normalized


# ── Organization schemas ──────────────────────────────────────────────────────

class CreateOrgRequest(BaseModel):
    name: str
    slug: str

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, v: str) -> str:
        return _validate_slug(v)


class UpdateOrgRequest(BaseModel):
    name: str | None = None


class OrgResponse(BaseModel):
    org_id: uuid.UUID
    name: str
    slug: str
    created_at: datetime

    model_config = {"from_attributes": True}


class OrgListResponse(BaseModel):
    items: list[OrgResponse]
    total: int


# ── Workspace schemas ─────────────────────────────────────────────────────────

class CreateWorkspaceRequest(BaseModel):
    name: str
    description: str | None = None


class UpdateWorkspaceRequest(BaseModel):
    name: str | None = None
    description: str | None = None


class WorkspaceResponse(BaseModel):
    workspace_id: uuid.UUID
    org_id: uuid.UUID
    name: str
    description: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class WorkspaceListResponse(BaseModel):
    items: list[WorkspaceResponse]
    total: int


# ── Membership schemas ────────────────────────────────────────────────────────

class AddMemberRequest(BaseModel):
    user_id: uuid.UUID
    org_role: str


class MemberResponse(BaseModel):
    org_id: uuid.UUID
    user_id: uuid.UUID
    org_role: str
    created_at: datetime

    model_config = {"from_attributes": True}


class MemberListResponse(BaseModel):
    items: list[MemberResponse]
    total: int

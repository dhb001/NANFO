"""NANFO Backend — Organization module Pydantic schemas.

Request/response schemas for organization, workspace, and membership endpoints.
All endpoints follow API_STANDARD.md §2 envelope via the responses module.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, StringConstraints, field_validator, model_validator

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
Description = Annotated[str, StringConstraints(max_length=4000)]
OrgRole = Literal["Admin", "Operator", "Read-Only"]


class UpdateRequest(BaseModel):
    @model_validator(mode="after")
    def validate_patch(self):
        if not self.model_fields_set or ("name" in self.model_fields_set and self.name is None):
            raise ValueError("Supply at least one field; name cannot be null.")
        return self


def _validate_slug(value: str) -> str:
    """Normalize and validate org slug: lowercase, alphanumeric + hyphens only."""
    normalized = value.lower().strip()
    if not re.fullmatch(r'[a-z0-9][a-z0-9\-]{1,61}[a-z0-9]', normalized):
        raise ValueError("Slug must be 3-63 characters, lowercase alphanumeric and hyphens only, and must not start or end with a hyphen.")
    return normalized


# ── Organization schemas ──────────────────────────────────────────────────────

class CreateOrgRequest(BaseModel):
    name: Name
    slug: str

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, v: str) -> str:
        return _validate_slug(v)


class UpdateOrgRequest(UpdateRequest):
    name: Name | None = None


class OrgResponse(BaseModel):
    org_id: uuid.UUID
    name: str
    slug: str
    created_at: datetime
    # ADR-028 C6: the caller's current role in this organization. Always set by
    # list/get (and create/update, whose caller is necessarily Admin).
    caller_role: OrgRole | None = None

    model_config = {"from_attributes": True}


class OrgListResponse(BaseModel):
    items: list[OrgResponse]
    total: int


# ── Workspace schemas ─────────────────────────────────────────────────────────

class CreateWorkspaceRequest(BaseModel):
    name: Name
    description: Description | None = None


class UpdateWorkspaceRequest(UpdateRequest):
    name: Name | None = None
    description: Description | None = None


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
    org_role: OrgRole


class MemberResponse(BaseModel):
    org_id: uuid.UUID
    user_id: uuid.UUID
    org_role: str
    created_at: datetime

    model_config = {"from_attributes": True}


class MemberListResponse(BaseModel):
    items: list[MemberResponse]
    total: int

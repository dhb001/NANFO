"""ADR-026 boundary validation regressions."""

import pytest
from pydantic import ValidationError

from app.modules.organization.schemas import (
    AddMemberRequest,
    CreateOrgRequest,
    CreateWorkspaceRequest,
    UpdateOrgRequest,
    UpdateWorkspaceRequest,
)


@pytest.mark.parametrize("slug", ["a", "ab", "a" * 64, "-abc", "abc-", "ab_c"])
def test_invalid_slug(slug):
    with pytest.raises(ValidationError):
        CreateOrgRequest(name="Organization", slug=slug)


@pytest.mark.parametrize("slug", ["abc", "a" * 63, "  North-Campus  "])
def test_normalized_bounded_slug(slug):
    assert CreateOrgRequest(name="Organization", slug=slug).slug == slug.strip().lower()


@pytest.mark.parametrize("schema", [CreateWorkspaceRequest, UpdateWorkspaceRequest, UpdateOrgRequest])
@pytest.mark.parametrize("name", ["", " \t", "x" * 256])
def test_blank_or_oversized_name(schema, name):
    with pytest.raises(ValidationError):
        schema(name=name)


@pytest.mark.parametrize("schema", [UpdateWorkspaceRequest, UpdateOrgRequest])
@pytest.mark.parametrize("payload", [{}, {"name": None}])
def test_empty_or_null_name_patch(schema, payload):
    with pytest.raises(ValidationError):
        schema(**payload)


def test_nullable_description_distinguishes_omission():
    assert "description" not in UpdateWorkspaceRequest(name="Rename").model_fields_set
    assert "description" in UpdateWorkspaceRequest(description=None).model_fields_set
    with pytest.raises(ValidationError):
        CreateWorkspaceRequest(name="Workspace", description="x" * 4001)


def test_member_roles_reject_unknown_values():
    with pytest.raises(ValidationError):
        AddMemberRequest(user_id="00000000-0000-0000-0000-000000000001", org_role="Owner")

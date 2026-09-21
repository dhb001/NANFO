"""Unit tests for workspace scope dependency helpers."""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from app.core.dependencies import (
    TokenClaims,
    enforce_org_scope,
    enforce_workspace_scope,
    get_claim_org_scope,
    get_claim_workspace_scope,
)


def _claims(*, workspace_id: str | None, org_id: str | None = None) -> TokenClaims:
    payload = {
        "sub": str(uuid.uuid4()),
        "email": "scope@example.com",
        "roles": ["Admin"],
        "permissions": ["read:topology"],
        "jti": str(uuid.uuid4()),
        "sid": str(uuid.uuid4()),
        "exp": 9999999999,
    }
    if org_id is not None:
        payload["org_id"] = org_id
    if workspace_id is not None:
        payload["workspace_id"] = workspace_id
    return TokenClaims(payload)


def test_enforce_workspace_scope_returns_request_workspace_when_claim_absent():
    workspace_id = uuid.uuid4()
    result = enforce_workspace_scope(claims=_claims(workspace_id=None), workspace_id=workspace_id)
    assert result == workspace_id


def test_enforce_workspace_scope_binds_claim_workspace_when_request_missing():
    claim_workspace_id = uuid.uuid4()
    result = enforce_workspace_scope(
        claims=_claims(workspace_id=str(claim_workspace_id)),
        workspace_id=None,
    )
    assert result == claim_workspace_id


def test_enforce_workspace_scope_rejects_workspace_mismatch():
    with pytest.raises(HTTPException) as exc_info:
        enforce_workspace_scope(
            claims=_claims(workspace_id=str(uuid.uuid4())),
            workspace_id=uuid.uuid4(),
        )

    assert exc_info.value.status_code == 403


def test_enforce_workspace_scope_rejects_invalid_claim_workspace_uuid():
    with pytest.raises(HTTPException) as exc_info:
        enforce_workspace_scope(
            claims=_claims(workspace_id="not-a-uuid"),
            workspace_id=uuid.uuid4(),
        )

    assert exc_info.value.status_code == 403


def test_enforce_org_scope_returns_request_org_when_claim_absent():
    org_id = uuid.uuid4()
    result = enforce_org_scope(claims=_claims(workspace_id=None, org_id=None), org_id=org_id)
    assert result == org_id


def test_enforce_org_scope_accepts_matching_org_claim():
    org_id = uuid.uuid4()
    result = enforce_org_scope(claims=_claims(workspace_id=None, org_id=str(org_id)), org_id=org_id)
    assert result == org_id


def test_enforce_org_scope_rejects_org_claim_mismatch():
    with pytest.raises(HTTPException) as exc_info:
        enforce_org_scope(
            claims=_claims(workspace_id=None, org_id=str(uuid.uuid4())),
            org_id=uuid.uuid4(),
        )

    assert exc_info.value.status_code == 403


def test_enforce_org_scope_rejects_invalid_claim_org_uuid():
    with pytest.raises(HTTPException) as exc_info:
        enforce_org_scope(
            claims=_claims(workspace_id=None, org_id="not-a-uuid"),
            org_id=uuid.uuid4(),
        )

    assert exc_info.value.status_code == 403


def test_get_claim_workspace_scope_returns_none_when_absent():
    assert get_claim_workspace_scope(claims=_claims(workspace_id=None)) is None


def test_get_claim_workspace_scope_returns_uuid_when_present():
    workspace_id = uuid.uuid4()
    assert get_claim_workspace_scope(claims=_claims(workspace_id=str(workspace_id))) == workspace_id


def test_get_claim_workspace_scope_rejects_invalid_uuid():
    with pytest.raises(HTTPException) as exc_info:
        get_claim_workspace_scope(claims=_claims(workspace_id="invalid"))
    assert exc_info.value.status_code == 403


def test_get_claim_org_scope_returns_none_when_absent():
    assert get_claim_org_scope(claims=_claims(workspace_id=None, org_id=None)) is None


def test_get_claim_org_scope_returns_uuid_when_present():
    org_id = uuid.uuid4()
    assert get_claim_org_scope(claims=_claims(workspace_id=None, org_id=str(org_id))) == org_id


def test_get_claim_org_scope_rejects_invalid_uuid():
    with pytest.raises(HTTPException) as exc_info:
        get_claim_org_scope(claims=_claims(workspace_id=None, org_id="invalid"))
    assert exc_info.value.status_code == 403

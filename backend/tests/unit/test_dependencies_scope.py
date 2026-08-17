"""Unit tests for workspace scope dependency helpers."""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from app.core.dependencies import TokenClaims, enforce_workspace_scope


def _claims(*, workspace_id: str | None) -> TokenClaims:
    payload = {
        "sub": str(uuid.uuid4()),
        "email": "scope@example.com",
        "roles": ["Admin"],
        "permissions": ["read:topology"],
        "jti": str(uuid.uuid4()),
        "exp": 9999999999,
    }
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

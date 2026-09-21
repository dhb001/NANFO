"""Strict signed claim validation and password utility regressions."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from jose import JWTError, jwt

from app.core.config import get_settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    remaining_ttl_seconds,
    verify_password,
)

USER_ID = str(uuid.UUID(int=1))


def test_password_hashing():
    hashed = hash_password("correct")
    assert hashed.startswith(("$2b$", "$2a$"))
    assert verify_password("correct", hashed)
    assert not verify_password("wrong", hashed)
    assert hashed != hash_password("correct")


def test_access_claim_baseline_and_optional_scope():
    sid, org_id, workspace_id = (str(uuid.uuid4()) for _ in range(3))
    token, jti = create_access_token(
        user_id=USER_ID, sid=sid, email="a@b.com", roles=["Admin"],
        permissions=["read:topology"], org_id=org_id, workspace_id=workspace_id,
    )
    claims = decode_token(token)
    assert claims == {
        "sub": USER_ID, "sid": sid, "email": "a@b.com", "roles": ["Admin"],
        "permissions": ["read:topology"], "org_id": org_id, "workspace_id": workspace_id,
        "token_type": "access", "jti": jti, "exp": claims["exp"], "iat": claims["iat"],
    }


def test_refresh_type_and_unique_jti():
    token, jti = create_refresh_token(user_id=USER_ID)
    claims = decode_token(token, token_type="refresh")
    assert claims["sub"] == USER_ID
    assert "roles" not in claims and "permissions" not in claims
    assert create_refresh_token(user_id=USER_ID)[1] != jti
    with pytest.raises(JWTError):
        decode_token(token)


@pytest.mark.parametrize("kind", ["access", "refresh"])
@pytest.mark.parametrize("field", ["sub", "sid", "jti", "iat", "exp", "token_type"])
def test_required_fields(kind, field):
    token = (create_refresh_token(user_id=USER_ID)[0] if kind == "refresh" else
             create_access_token(user_id=USER_ID, email="a@b.com", roles=[], permissions=[])[0])
    claims = decode_token(token, token_type=kind)
    del claims[field]
    settings = get_settings()
    malformed = jwt.encode(claims, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    with pytest.raises(JWTError):
        decode_token(malformed, token_type=kind)


@pytest.mark.parametrize(("field", "value"), [
    ("sub", "bad"), ("sid", []), ("jti", 4), ("iat", True), ("exp", "9999999999"),
    ("roles", "Admin"), ("roles", [1]), ("permissions", None), ("permissions", [False]),
    ("email", 5), ("org_id", "bad"), ("workspace_id", []), ("token_type", "refresh"),
    ("iat", 9999999999), ("exp", 0), ("hashed_password", "excluded"),
])
def test_malformed_claims(field, value):
    token, _ = create_access_token(user_id=USER_ID, email="a@b.com", roles=[], permissions=[])
    claims = decode_token(token)
    claims[field] = value
    settings = get_settings()
    token = jwt.encode(claims, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    with pytest.raises(JWTError):
        decode_token(token)


@pytest.mark.parametrize("field", ["roles", "permissions", "email"])
def test_required_access_fields(field):
    token, _ = create_access_token(user_id=USER_ID, email="a@b.com", roles=[], permissions=[])
    claims = decode_token(token)
    del claims[field]
    settings = get_settings()
    with pytest.raises(JWTError):
        decode_token(jwt.encode(claims, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM))


def test_tampering_and_ttl():
    token, _ = create_access_token(user_id=USER_ID, email="a@b.com", roles=[], permissions=[])
    with pytest.raises(JWTError):
        decode_token(token[:-5] + "XXXXX")
    assert remaining_ttl_seconds(int((datetime.now(UTC) + timedelta(minutes=1)).timestamp())) > 0
    assert remaining_ttl_seconds(0) == 0

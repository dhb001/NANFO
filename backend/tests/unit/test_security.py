"""Unit tests for app/core/security.py.

Tests JWT creation, decoding, password hashing, and revocation TTL calculation.
No external dependencies — pure algorithmic tests.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from jose import JWTError

from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    remaining_ttl_seconds,
    verify_password,
)


class TestPasswordHashing:
    def test_hash_produces_bcrypt_hash(self):
        h = hash_password("secret")
        assert h.startswith(("$2b$", "$2a$"))

    def test_verify_correct_password(self):
        h = hash_password("correct")
        assert verify_password("correct", h) is True

    def test_verify_wrong_password(self):
        h = hash_password("correct")
        assert verify_password("wrong", h) is False

    def test_two_hashes_of_same_password_differ(self):
        """bcrypt generates unique salts — hashes must not be identical."""
        h1 = hash_password("same")
        h2 = hash_password("same")
        assert h1 != h2


class TestJWTAccessToken:
    def test_create_access_token_returns_string_and_jti(self):
        token, jti = create_access_token(
            user_id="u1",
            email="a@b.com",
            roles=["Admin"],
            permissions=["read:topology"],
        )
        assert isinstance(token, str) and len(token) > 20
        assert isinstance(jti, str)
        # jti must be a valid UUID
        uuid.UUID(jti)

    def test_decoded_contains_required_claims(self):
        """All required claims from Authentication.md §8.1 must be present."""
        token, _jti = create_access_token(
            user_id="u1",
            email="a@b.com",
            roles=["Operator"],
            permissions=["read:topology"],
        )
        payload = decode_token(token)
        for claim in ("sub", "email", "roles", "permissions", "iat", "exp", "jti"):
            assert claim in payload, f"Required claim '{claim}' missing"

    def test_optional_org_id_included_when_provided(self):
        """org_id is optional — only included when provided (Authentication.md §8.2)."""
        org_id = str(uuid.uuid4())
        token, _ = create_access_token(
            user_id="u1", email="a@b.com", roles=[], permissions=[], org_id=org_id
        )
        payload = decode_token(token)
        assert payload["org_id"] == org_id

    def test_org_id_absent_when_not_provided(self):
        """org_id must not appear in the token when not provided."""
        token, _ = create_access_token(
            user_id="u1", email="a@b.com", roles=[], permissions=[]
        )
        payload = decode_token(token)
        assert "org_id" not in payload

    def test_optional_workspace_id_included_when_provided(self):
        ws_id = str(uuid.uuid4())
        token, _ = create_access_token(
            user_id="u1", email="a@b.com", roles=[], permissions=[], workspace_id=ws_id
        )
        payload = decode_token(token)
        assert payload["workspace_id"] == ws_id

    def test_hashed_password_absent_from_token(self):
        """Authentication.md §8.4 exclusion: hashed_password must not appear in any token."""
        token, _ = create_access_token(
            user_id="u1", email="a@b.com", roles=[], permissions=[]
        )
        payload = decode_token(token)
        assert "hashed_password" not in payload
        assert "password" not in payload

    def test_decode_fails_on_tampered_token(self):
        token, _ = create_access_token(user_id="u1", email="a@b.com", roles=[], permissions=[])
        tampered = token[:-5] + "XXXXX"
        with pytest.raises(JWTError):
            decode_token(tampered)

    def test_two_tokens_have_different_jtis(self):
        """Each token issuance must produce a unique jti for revocation support."""
        _, jti1 = create_access_token(user_id="u1", email="a@b.com", roles=[], permissions=[])
        _, jti2 = create_access_token(user_id="u1", email="a@b.com", roles=[], permissions=[])
        assert jti1 != jti2


class TestJWTRefreshToken:
    def test_refresh_token_has_token_type_claim(self):
        token, _ = create_refresh_token(user_id="u1")
        payload = decode_token(token)
        assert payload.get("token_type") == "refresh"

    def test_refresh_token_contains_sub(self):
        token, _ = create_refresh_token(user_id="u1")
        payload = decode_token(token)
        assert payload["sub"] == "u1"

    def test_refresh_token_does_not_contain_roles(self):
        """Refresh tokens are minimal — no roles or permissions (Authentication.md §5)."""
        token, _ = create_refresh_token(user_id="u1")
        payload = decode_token(token)
        assert "roles" not in payload
        assert "permissions" not in payload


class TestRemainingTTL:
    def test_future_exp_returns_positive_value(self):
        future = int((datetime.now(UTC) + timedelta(minutes=15)).timestamp())
        ttl = remaining_ttl_seconds(future)
        assert ttl > 0

    def test_past_exp_returns_zero(self):
        past = int((datetime.now(UTC) - timedelta(minutes=1)).timestamp())
        ttl = remaining_ttl_seconds(past)
        assert ttl == 0

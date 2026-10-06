"""ADR-028 C10/C11/C19: PyJWT claims, key rotation overlap, algorithm pinning and bcrypt bounds."""

from __future__ import annotations

import base64
import json
import time
import uuid
from types import SimpleNamespace

import bcrypt
import jwt as pyjwt
import pytest

from app.core import security
from app.core.config import get_settings
from app.core.security import (
    BCRYPT_MAX_PASSWORD_BYTES,
    TOKEN_AUDIENCE,
    TOKEN_ISSUER,
    JWTError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    password_within_bcrypt_limit,
    verify_password,
)
from tests.jwt_support import jwt as test_jwt

USER_ID = str(uuid.UUID(int=1))
CURRENT_KEY = get_settings().JWT_SECRET_KEY
PREVIOUS_KEY = "previous-signing-key-0123456789-abcdef"


def _settings(**overrides):
    base = get_settings()
    values = {
        "JWT_SECRET_KEY": base.JWT_SECRET_KEY, "JWT_ALGORITHM": base.JWT_ALGORITHM,
        "JWT_ACCESS_TOKEN_EXPIRE_MINUTES": base.JWT_ACCESS_TOKEN_EXPIRE_MINUTES,
        "JWT_REFRESH_TOKEN_EXPIRE_DAYS": base.JWT_REFRESH_TOKEN_EXPIRE_DAYS,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _access_claims(**overrides):
    token, _ = create_access_token(user_id=USER_ID, email="a@b.com", roles=["Admin"], permissions=[])
    claims = decode_token(token)
    claims.update(overrides)
    return claims


def test_jwt_error_is_the_pyjwt_base_exception():
    from app.main import app

    assert JWTError is pyjwt.PyJWTError
    assert issubclass(pyjwt.ExpiredSignatureError, JWTError)
    assert JWTError in app.exception_handlers  # the exported name is what the app maps to 401


def test_issued_tokens_carry_issuer_and_audience_but_decoded_claims_do_not():
    for token in (create_access_token(user_id=USER_ID, email="a@b.com", roles=[], permissions=[])[0],
                  create_refresh_token(user_id=USER_ID)[0]):
        raw = pyjwt.decode(token, options={"verify_signature": False})
        assert (raw["iss"], raw["aud"]) == (TOKEN_ISSUER, TOKEN_AUDIENCE) == ("nanfo-api", "nanfo")
        header = json.loads(base64.urlsafe_b64decode(token.split(".")[0] + "=="))
        assert header["alg"] == "HS256"
    claims = decode_token(create_access_token(user_id=USER_ID, email="a@b.com", roles=[], permissions=[])[0])
    assert "iss" not in claims and "aud" not in claims


@pytest.mark.parametrize("claim", ["iss", "aud"])
def test_missing_issuer_or_audience_is_rejected(claim):
    claims = {**_access_claims(), "iss": TOKEN_ISSUER, "aud": TOKEN_AUDIENCE}
    del claims[claim]
    token = test_jwt.encode(claims, CURRENT_KEY, algorithm="HS256", registered=False)
    with pytest.raises(JWTError):
        decode_token(token)


@pytest.mark.parametrize(("claim", "value"), [
    ("iss", "someone-else"), ("aud", "other"), ("aud", ["nanfo", "other"]), ("iss", ""),
])
def test_wrong_issuer_or_audience_is_rejected(claim, value):
    claims = {**_access_claims(), "iss": TOKEN_ISSUER, "aud": TOKEN_AUDIENCE, claim: value}
    with pytest.raises(JWTError):
        decode_token(test_jwt.encode(claims, CURRENT_KEY, algorithm="HS256", registered=False))


@pytest.mark.parametrize(("offset", "accepted"), [(-20, True), (-45, False)])
def test_expiry_allows_thirty_second_leeway(offset, accepted):
    now = int(time.time())
    claims = _access_claims(iat=now - 900, exp=now + offset)
    token = test_jwt.encode(claims, CURRENT_KEY, algorithm="HS256")
    if accepted:
        assert decode_token(token)["exp"] == now + offset
    else:
        with pytest.raises(JWTError):
            decode_token(token)


@pytest.mark.parametrize(("offset", "accepted"), [(20, True), (45, False)])
def test_issued_at_allows_thirty_second_clock_skew(offset, accepted):
    now = int(time.time())
    token = test_jwt.encode(_access_claims(iat=now + offset, exp=now + 900), CURRENT_KEY, algorithm="HS256")
    if accepted:
        assert decode_token(token)["iat"] == now + offset
    else:
        with pytest.raises(JWTError):
            decode_token(token)


@pytest.mark.filterwarnings("ignore::jwt.warnings.InsecureKeyLengthWarning")  # crafting with the test key
@pytest.mark.parametrize("algorithm", ["HS384", "HS512"])
def test_only_the_configured_algorithm_is_accepted(algorithm):
    token = test_jwt.encode(_access_claims(), CURRENT_KEY, algorithm=algorithm)
    with pytest.raises(JWTError):
        decode_token(token)


def test_unsigned_none_algorithm_is_rejected():
    header = base64.urlsafe_b64encode(json.dumps({"alg": "none", "typ": "JWT"}).encode()).rstrip(b"=")
    claims = {**_access_claims(), "iss": TOKEN_ISSUER, "aud": TOKEN_AUDIENCE}
    body = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=")
    with pytest.raises(JWTError):
        decode_token(f"{header.decode()}.{body.decode()}.")


def test_asymmetric_algorithm_confusion_is_rejected():
    # An attacker-chosen RS256 header must not make the HMAC secret act as a public key.
    token = test_jwt.encode(_access_claims(), CURRENT_KEY, algorithm="HS256")
    header = base64.urlsafe_b64encode(json.dumps({"alg": "RS256", "typ": "JWT"}).encode()).rstrip(b"=")
    forged = ".".join([header.decode(), *token.split(".")[1:]])
    with pytest.raises(JWTError):
        decode_token(forged)


@pytest.mark.parametrize("algorithm", ["none", "RS256", "HS1", ""])
def test_unsupported_configured_algorithm_fails_loudly(monkeypatch, algorithm):
    monkeypatch.setattr(security, "_settings", lambda: _settings(JWT_ALGORITHM=algorithm))
    with pytest.raises(RuntimeError, match="JWT_ALGORITHM"):
        create_refresh_token(user_id=USER_ID)


@pytest.mark.parametrize("algorithm", ["HS384", "HS512"])
def test_configured_hs_algorithms_round_trip(monkeypatch, algorithm):
    key = "k" * 64
    monkeypatch.setattr(security, "_settings", lambda: _settings(JWT_ALGORITHM=algorithm, JWT_SECRET_KEY=key))
    token, jti = create_refresh_token(user_id=USER_ID)
    assert decode_token(token, token_type="refresh")["jti"] == jti
    assert json.loads(base64.urlsafe_b64decode(token.split(".")[0] + "=="))["alg"] == algorithm


@pytest.mark.parametrize("previous", [
    PREVIOUS_KEY, f" other-retired-signing-key-0123456789 , {PREVIOUS_KEY} ", ["other-retired-signing-key-0123456789", PREVIOUS_KEY],
])
def test_previous_keys_verify_but_never_sign(monkeypatch, previous):
    monkeypatch.setattr(security, "_settings", lambda: _settings(JWT_SECRET_KEY=PREVIOUS_KEY))
    old_token, _ = create_refresh_token(user_id=USER_ID)
    monkeypatch.setattr(security, "_settings", lambda: _settings(JWT_PREVIOUS_SECRET_KEYS=previous))
    assert decode_token(old_token, token_type="refresh")["sub"] == USER_ID
    new_token, _ = create_refresh_token(user_id=USER_ID)
    # New tokens are signed with the current key only.
    pyjwt.decode(new_token, CURRENT_KEY, algorithms=["HS256"], audience=TOKEN_AUDIENCE)
    with pytest.raises(pyjwt.InvalidSignatureError):
        pyjwt.decode(new_token, PREVIOUS_KEY, algorithms=["HS256"], audience=TOKEN_AUDIENCE)


def test_retired_key_is_rejected_without_overlap(monkeypatch):
    monkeypatch.setattr(security, "_settings", lambda: _settings(JWT_SECRET_KEY=PREVIOUS_KEY))
    old_token, _ = create_refresh_token(user_id=USER_ID)
    monkeypatch.setattr(security, "_settings", lambda: _settings(JWT_PREVIOUS_SECRET_KEYS=""))
    with pytest.raises(JWTError):
        decode_token(old_token, token_type="refresh")


def test_previous_key_cannot_rescue_an_expired_token(monkeypatch):
    now = int(time.time())
    claims = {**_access_claims(), "iat": now - 3600, "exp": now - 600}
    monkeypatch.setattr(security, "_settings", lambda: _settings(JWT_PREVIOUS_SECRET_KEYS=PREVIOUS_KEY))
    with pytest.raises(pyjwt.ExpiredSignatureError):
        decode_token(test_jwt.encode(claims, PREVIOUS_KEY, algorithm="HS256"))


@pytest.mark.parametrize("secret", [None, "", "   "])
def test_worker_without_signing_key_fails_clearly(monkeypatch, secret):
    monkeypatch.setattr(security, "_settings", lambda: _settings(JWT_SECRET_KEY=secret, NANFO_SERVICE_ROLE="worker"))
    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY is not configured for NANFO_SERVICE_ROLE=worker"):
        create_access_token(user_id=USER_ID, email="a@b.com", roles=[], permissions=[])
    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
        decode_token("header.payload.signature")


def test_secret_str_keys_are_unwrapped(monkeypatch):
    from pydantic import SecretStr

    monkeypatch.setattr(security, "_settings", lambda: _settings(
        JWT_SECRET_KEY=SecretStr(CURRENT_KEY), JWT_PREVIOUS_SECRET_KEYS=SecretStr(PREVIOUS_KEY)))
    token, _ = create_refresh_token(user_id=USER_ID)
    assert decode_token(token, token_type="refresh")["sub"] == USER_ID


# ── bcrypt 72-byte bound (C11) ────────────────────────────────────────────────

def test_hash_password_rejects_more_than_72_utf8_bytes():
    assert password_within_bcrypt_limit("a" * BCRYPT_MAX_PASSWORD_BYTES)
    assert not password_within_bcrypt_limit("a" * (BCRYPT_MAX_PASSWORD_BYTES + 1))
    # 36 two-byte characters are exactly 72 bytes; one more is 74.
    assert password_within_bcrypt_limit("é" * 36)
    assert not password_within_bcrypt_limit("é" * 37)
    with pytest.raises(ValueError, match="72-byte"):
        hash_password("é" * 37)
    with pytest.raises(ValueError):
        hash_password("\ud800")


def test_over_long_secret_never_verifies_as_its_prefix(monkeypatch):
    monkeypatch.setattr(security, "_BCRYPT_ROUNDS", 4)
    prefix = "p" * BCRYPT_MAX_PASSWORD_BYTES
    stored = hash_password(prefix)
    assert verify_password(prefix, stored)
    # bcrypt 4.x itself would accept this (it truncates at 72 bytes).
    assert bcrypt.checkpw((prefix + "suffix").encode(), stored.encode())
    assert not verify_password(prefix + "suffix", stored)
    assert not verify_password("\ud800", stored)

"""Hand-crafted JWTs for tests (PyJWT; python-jose removed by ADR-028 C10).

Production tokens always carry ``iss="nanfo-api"`` and ``aud="nanfo"`` and the
decoder requires both. Tests that re-sign deliberately malformed claim sets use
this signer so the claim under test — not a missing transport claim — is what
the production decoder rejects. ``registered=False`` crafts a token without
iss/aud to exercise that rejection explicitly.
"""

from __future__ import annotations

from typing import Any

import jwt as _pyjwt

from app.core.security import TOKEN_AUDIENCE, TOKEN_ISSUER


class _TestJWT:
    """Small jose-compatible facade (``encode``/``get_unverified_claims``)."""

    @staticmethod
    def encode(claims: dict[str, Any], key: str, algorithm: str = "HS256", *, registered: bool = True) -> str:
        payload = dict(claims)
        if registered:
            payload.setdefault("iss", TOKEN_ISSUER)
            payload.setdefault("aud", TOKEN_AUDIENCE)
        return _pyjwt.encode(payload, key, algorithm=algorithm)

    @staticmethod
    def get_unverified_claims(token: str) -> dict[str, Any]:
        claims = _pyjwt.decode(token, options={"verify_signature": False})
        claims.pop("iss", None)
        claims.pop("aud", None)
        return claims


jwt = _TestJWT()

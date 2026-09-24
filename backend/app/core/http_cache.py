"""Digest ETag helpers shared by every binary download route (ADR-028).

All content-addressed downloads use one strong ETag convention,
``"sha256:<lowercase hex>"``, and honour ``If-None-Match`` with ``304``.
"""

from __future__ import annotations

import re

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def digest_etag(sha256_hex: str) -> str:
    """Return the canonical strong ETag for a SHA-256 hex digest."""
    value = sha256_hex.strip().lower()
    if not _HEX64.fullmatch(value):
        raise ValueError("sha256 digest must be 64 lowercase hex characters")
    return f'"sha256:{value}"'


def if_none_match_satisfied(header_value: str | None, etag: str) -> bool:
    """RFC 9110 weak comparison of ``If-None-Match`` against ``etag``.

    Accepts ``*``, comma-separated lists and ``W/`` weak validators.
    """
    if not header_value:
        return False
    target = etag.removeprefix("W/")
    for candidate in header_value.split(","):
        candidate = candidate.strip()
        if candidate == "*":
            return True
        if candidate.removeprefix("W/") == target:
            return True
    return False

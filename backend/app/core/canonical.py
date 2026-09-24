"""Canonical JSON serialization and SHA-256 digests (ADR-028).

This reproduces, byte for byte, the convention already used by the intent lab,
simulation evaluator, report artifacts and frozen model diagnostics:
``json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)``
with ASCII output. Historical digests therefore remain valid.

Call sites with *different* semantics (NaN-tolerant or ``default=str``) must not
switch to this helper; they keep explicitly named local variants.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json_bytes(value: Any) -> bytes:
    """Deterministic, strict JSON encoding (sorted keys, compact, no NaN/Infinity)."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("ascii")


def canonical_sha256(value: Any) -> str:
    """Lowercase hex SHA-256 of :func:`canonical_json_bytes`."""
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()

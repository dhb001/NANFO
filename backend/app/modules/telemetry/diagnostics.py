"""Credential-free failure diagnostics: fixed codes plus exception class, counted.

Collector and owner-boundary failures must never log exception messages (driver,
database and Redis errors can embed DSNs, hosts or secrets). Only a fixed code
from an allow-listed grammar and ``type(exc).__name__`` are emitted.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from app.modules.telemetry.snmp_config import SNMPError

_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def failure_code(exc: BaseException, *, default: str) -> str:
    """``SNMPError`` messages are fixed codes by contract; everything else maps to ``default``."""
    if isinstance(exc, SNMPError) and _CODE.fullmatch(str(exc)):
        return str(exc)
    if isinstance(exc, TimeoutError):
        return f"{default}_timeout" if _CODE.fullmatch(f"{default}_timeout") else default
    return default


class FailureCounter:
    """Per-component counts by fixed code (exported in worker health documents)."""

    def __init__(self) -> None:
        self._counts: Counter[str] = Counter()

    def record(self, logger: Any, event: str, exc: BaseException, *, default: str, **context: Any) -> str:
        code = failure_code(exc, default=default)
        self._counts[code] += 1
        logger.warning(event, error_code=code, error_type=type(exc).__name__, **context)
        return code

    def note(self, logger: Any, event: str, code: str, **context: Any) -> str:
        """Count a non-exception condition identified only by a fixed code."""
        code = code if _CODE.fullmatch(code) else "unclassified"
        self._counts[code] += 1
        logger.warning(event, error_code=code, **context)
        return code

    def snapshot(self) -> dict[str, int]:
        return dict(sorted(self._counts.items()))


# Process-wide counter for boundaries without an owning worker health document.
OWNER_BOUNDARY_FAILURES = FailureCounter()

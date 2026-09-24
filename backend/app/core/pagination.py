"""Shared page-number bounds for offset-paginated list routes (ADR-028).

Unbounded ``page`` values can overflow the int64 OFFSET encoding (HTTP 500)
and force arbitrarily deep scans. Every ``page`` query parameter uses
:data:`PageNumber` (or ``le=MAX_PAGE``).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Query

MAX_PAGE = 10_000

PageNumber = Annotated[int, Query(ge=1, le=MAX_PAGE, description="1-based page number")]

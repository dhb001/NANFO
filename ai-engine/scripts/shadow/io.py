"""Bounded read-only operator imports; no paths or executable providers from JSON."""

import hashlib
import json
import os
import re
import stat
from datetime import datetime
from pathlib import Path

from .evaluate import diagnosticFromExport, evaluate
from .schemas import Decision, Outcomes, Plan

LIMIT = 8 * 1024 * 1024


def readPinned(path: Path, pin: str, *, limit: int = LIMIT) -> bytes:
    if not re.fullmatch(r"[a-f0-9]{64}", pin):
        raise ValueError("invalid SHA256 pin")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= limit:
            raise ValueError("artifact must be a bounded nonempty regular file")
        data = source.read(limit + 1)
    if len(data) > limit or hashlib.sha256(data).hexdigest() != pin:
        raise ValueError("artifact size or hash mismatch")
    return data


def parseJson(content: bytes) -> dict:
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError("duplicate JSON key")
            value[key] = item
        return value

    def invalidConstant(value):
        raise ValueError("nonfinite JSON number")

    def bounded(value, depth=0):
        if depth > 24:
            raise ValueError("JSON depth bound")
        if isinstance(value, (dict, list)):
            if len(value) > 10000:
                raise ValueError("JSON collection bound")
            for item in value.values() if isinstance(value, dict) else value:
                bounded(item, depth + 1)

    try:
        value = json.loads(content, object_pairs_hook=pairs, parse_constant=invalidConstant)
        bounded(value)
        # Also rejects overflowing JSON numeric literals (e.g. 1e999).
        json.dumps(value, allow_nan=False)
    except (UnicodeError, RecursionError) as exc:
        raise ValueError("invalid JSON encoding or nesting") from exc
    if not isinstance(value, dict):
        raise ValueError("JSON object required")
    return value


def loadEvaluation(
    *,
    plan_path: Path,
    plan_sha256: str,
    diagnostic_path: Path,
    outcomes_path: Path,
    benchmark_path: Path,
    now: datetime,
) -> Decision:
    plan_data = parseJson(readPinned(plan_path, plan_sha256, limit=1024 * 1024))
    plan = Plan.model_validate_json(json.dumps(plan_data))
    diagnostic_data = parseJson(readPinned(diagnostic_path, plan.diagnostic_sha256))
    outcome_data = parseJson(readPinned(outcomes_path, plan.outcomes_sha256))
    # Original benchmark is bound, not silently requalified by reading an export.
    readPinned(benchmark_path, plan.model.benchmark_evidence_sha256)
    diagnostic = diagnosticFromExport(diagnostic_data, plan)
    outcomes = Outcomes.model_validate_json(json.dumps(outcome_data))
    return evaluate(plan, diagnostic, outcomes, now=now, plan_sha256=plan_sha256)

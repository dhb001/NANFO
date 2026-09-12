"""Private, bounded, append-only evidence and exact Docker ownership checks."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

VERSION = "adr019.step14.v1"
OWNER_LABEL = "nanfo.acceptance.owner"
STAGE_LABEL = "nanfo.acceptance.stage"
MAX_JSON = 16 * 1024 * 1024
NAME = re.compile(r"nanfo-(?:acceptance|execution|override|report)-(?:postgres|pg|redis|neo|neo4j|lab)-[0-9a-f]{32}\Z")
ID = re.compile(r"[0-9a-f]{64}\Z")
IMAGE = re.compile(r"sha256:[0-9a-f]{64}\Z")


class Blocked(Exception):
    """Fixed reason codes only, never upstream exception messages."""


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def sha(value: bytes):
    return hashlib.sha256(value).hexdigest()


def write_new(path: Path, value):
    data = encoded(value)
    if len(data) > MAX_JSON:
        raise Blocked("evidence_size_bound")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def read_json(path: Path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        import stat

        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise Blocked("evidence_not_regular")
        data = stream.read(MAX_JSON + 1)
    if len(data) > MAX_JSON:
        raise Blocked("evidence_size_bound")
    return json.loads(data), sha(data)


def sanitize(value):
    """Withhold sensitive fields and diagnostic text rather than guessing tokens."""
    if isinstance(value, dict):
        return {key: sanitize(item) for key, item in value.items()
                if not re.search(r"password|secret|token|authorization|traceback|stack|dsn", key, re.I)
                and key not in {"failure", "failure_reason", "error", "error_context", "postgres_tests"}}
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, str):
        if re.search(r"(?i)bearer\s|://|traceback|\btoken\b|\bpassword\b|\bsecret\b|File \".*line \d", value):
            return "[diagnostic withheld]"
        return value[:65536]
    return value


class Ledger:
    """Each event is an exclusive fsynced file; interrupted runs remain inspectable."""

    def __init__(self, directory: Path):
        self.directory = directory
        self.sequence = 0
        self.previous = None
        for path in sorted(directory.glob("event-*.json")):
            event, digest = read_json(path)
            if event["sequence"] != self.sequence or event["previous_sha256"] != self.previous:
                raise Blocked("ledger_chain_invalid")
            self.sequence += 1
            self.previous = digest

    def append(self, kind, data):
        event = {"version": VERSION, "sequence": self.sequence,
                 "previous_sha256": self.previous, "kind": kind, "data": sanitize(data)}
        write_new(self.directory / f"event-{self.sequence:05d}.json", event)
        self.previous = sha(encoded(event))
        self.sequence += 1


def owned(container, *, owner, stage, baseline, names):
    """Labels alone or a familiar prefix alone never authorize removal."""
    labels = container.get("Labels") or {}
    return (bool(ID.fullmatch(container.get("Id", "")))
            and container["Id"] not in baseline
            and container.get("Name", "").lstrip("/") in names
            and bool(NAME.fullmatch(container.get("Name", "").lstrip("/")))
            and labels.get(OWNER_LABEL) == owner and labels.get(STAGE_LABEL) == stage)


def metrics():
    return {name: {"value": None, "unit": unit, "count": None, "raw_reference": None}
            for name, unit in (("goodput", "Mbps"), ("rtt", "ms"), ("probe_loss", "%"),
                               ("queue_backlog", "bytes"), ("recovery", "s"),
                               ("delivered", "bytes"), ("packet_delivery_ratio", "%"))}

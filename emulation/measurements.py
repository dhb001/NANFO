"""Bounded file publication and parsers; no runtime dependencies."""

import json
import math
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

MAX_BYTES = 1024 * 1024


def utcNow():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def atomicJson(path, value):
    path = Path(path)
    data = json.dumps(value, allow_nan=False, separators=(",", ":")).encode("utf-8")
    if len(data) > MAX_BYTES:
        raise ValueError("JSON exceeds 1 MiB publication limit")
    fd, temporary = tempfile.mkstemp(prefix=".publish-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
            os.fchmod(stream.fileno(), 0o644)
        os.replace(temporary, path)
        directory = os.open(str(path.parent), os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def readJson(path):
    with open(path, "rb") as stream:
        data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("JSON exceeds 1 MiB read limit")
    return json.loads(data)


def parseQueue(text):
    """Use only a single leaf netem; HTB parent backlog is the same packets."""
    try:
        rows = json.loads(text)
        if not isinstance(rows, list) or len(rows) > 64:
            return None
        leaves = [
            r
            for r in rows
            if r.get("kind") == "netem"
            and not any(
                child.get("parent", "").split(":")[0] == r.get("handle", "").split(":")[0]
                for child in rows
                if child is not r
            )
        ]
        if len(leaves) != 1:
            return None
        row = leaves[0]
        # iproute2 JSON uses top-level backlog (bytes) and qlen (packets).
        byteCount, packetCount = row.get("backlog"), row.get("qlen")
        if any(type(v) is not int or v < 0 for v in (byteCount, packetCount)):
            return None
        return {"backlog_bytes": byteCount, "backlog_packets": packetCount}
    except (ValueError, TypeError, AttributeError):
        return None


def parsePing(text, source, destination, interval, observedAt):
    counts = re.search(r"(\d+) packets transmitted, (\d+) (?:packets )?received", text)
    if not counts or not math.isfinite(interval) or interval <= 0:
        return None
    sent, received = map(int, counts.groups())
    if not 0 <= received <= sent <= 100:
        return None
    timing = re.search(r"(?:rtt|round-trip).*?= [\d.]+/([\d.]+)/", text)
    average = float(timing.group(1)) if timing else None
    if average is not None and (not math.isfinite(average) or average < 0):
        return None
    if received and average is None:
        return None
    return {
        "src_host": source,
        "dst_host": destination,
        "observed_at": observedAt,
        "sent": sent,
        "received": received,
        "rtt_avg_ms": average,
        "interval_seconds": interval,
    }


class MultipartReplies:
    """Correlate both stats kinds by polling round and XID; discard partial rounds."""

    def __init__(self):
        self.pending = {}
        self.complete = {}

    def begin(self, dpid, portXid, flowXid, now):
        self.pending[dpid] = {
            "started": now,
            "xids": {"ports": portXid, "flows": flowXid},
            "parts": {"ports": [], "flows": []},
            "done": set(),
        }

    def receive(self, dpid, kind, xid, rows, more, timestamp, now):
        entry = self.pending.get(dpid)
        if not entry or now - entry["started"] > 5 or entry["xids"][kind] != xid:
            return
        if kind in entry["done"]:
            return
        entry["parts"][kind].extend(rows)
        if len(entry["parts"][kind]) > (128 if kind == "ports" else 256):
            self.pending.pop(dpid, None)
            self.complete.pop(dpid, None)
            return
        if not more:
            entry["done"].add(kind)
        if len(entry["done"]) == 2:
            self.complete[dpid] = (now, {"dpid": dpid, "observed_at": timestamp, **entry["parts"]})
            del self.pending[dpid]

    def samples(self, now):
        return [sample for received, sample in self.complete.values() if now - received <= 6]

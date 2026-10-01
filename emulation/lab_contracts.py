"""Versioned stdlib-only lab contracts shared by the lab (Python 3.9) and the backend.

Importing this module never imports Mininet, os-ken, FRR drivers or application code.
The values mirror the frozen v4 lab files and the ai-engine routing contract; drift is
test-enforced (emulation/tests/test_lab_contracts.py), never silently re-derived.
"""

import hashlib
import hmac
import json
import os
import re
import stat
import tempfile
from pathlib import Path

CONTRACT_VERSION = "nanfo.lab-contracts/v1"

# Topology and action map (campus-small-v1; frozen v4 ospf.PATHS / matched.TABLES).
TOPOLOGY_ID = "campus-small-v1"
ROUTERS = ("core", "dist1", "dist2", "access1", "access2")
ACTION_PATHS = (("access1", "dist1", "access2"), ("access1", "dist2", "access2"))
ACTION_IDS = ("route0", "route1")
ROUTE_PAIRS = (("h1", "h3"), ("h3", "h1"), ("h2", "h4"), ("h4", "h2"))
FOREGROUND_PAIRS = (("h1", "h3"), ("h3", "h1"))
RESERVED_TABLES = (19110, 19111)
UDP_DATAGRAM_BYTES = 1200

# C15 mailbox command authentication.
COMMAND_KEY_ENV = "NANFO_LAB_COMMAND_KEY_FILE"
COMMAND_MAC_FIELD = "hmac_sha256"
MIN_KEY_BYTES = 32
MAX_KEY_BYTES = 16384
PUBLIC_FILE_MODE = 0o640

_HEX64 = re.compile(r"[0-9a-f]{64}")


def canonical(value):
    """Strict canonical JSON, byte-identical to app.core.canonical.canonical_json_bytes."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("ascii")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def action_map():
    """Wire action map: {"0": [...], "1": [...]} (ai-engine contracts.ACTION_MAP order)."""
    return {str(index): list(path) for index, path in enumerate(ACTION_PATHS)}


def action_index(action_id):
    if action_id not in ACTION_IDS:
        raise ValueError("unknown_action_id")
    return ACTION_IDS.index(action_id)


def expected_nodes(action, source, destination):
    """Complete kernel node path (hosts included) for a foreground pair under an action."""
    if type(action) is not int or not 0 <= action < len(ACTION_PATHS):
        raise ValueError("invalid_action")
    if (source, destination) not in FOREGROUND_PAIRS:
        raise ValueError("not_a_foreground_pair")
    path = ACTION_PATHS[action] if source < destination else tuple(reversed(ACTION_PATHS[action]))
    return [source, *path, destination]


def validate_route_readback(paths, action):
    """True only when both foreground directions report the action and its exact nodes."""
    if not isinstance(paths, dict):
        return False
    for source, destination in FOREGROUND_PAIRS:
        row = paths.get(f"{source}->{destination}")
        if (not isinstance(row, dict) or row.get("action") != action
                or row.get("nodes") != expected_nodes(action, source, destination)):
            return False
    return True


def reserved_slots():
    return [f"{node}:{table}" for node in ROUTERS for table in RESERVED_TABLES]


def contract_document():
    return {"version": CONTRACT_VERSION, "topology_id": TOPOLOGY_ID, "routers": list(ROUTERS),
            "action_ids": list(ACTION_IDS), "action_map": action_map(),
            "route_pairs": [list(pair) for pair in ROUTE_PAIRS],
            "foreground_pairs": [list(pair) for pair in FOREGROUND_PAIRS],
            "reserved_tables": list(RESERVED_TABLES), "udp_datagram_bytes": UDP_DATAGRAM_BYTES,
            "command_mac_field": COMMAND_MAC_FIELD}


def contract_sha256():
    return digest(contract_document())


def _fsync_directory(directory):
    fd = os.open(str(directory), os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_publish(path, data, *, mode=PUBLIC_FILE_MODE, limit=None):
    """Same-directory temporary, fsync, exact mode, parent-directory group, rename, dir fsync.

    A lab without CAP_CHOWN may still hand the file to the reader group: the owner may
    set any group it is a member of (Compose ``group_add``). Failure is never silent.
    """
    path = Path(path)
    if limit is not None and len(data) > limit:
        raise ValueError("publication_too_large")
    if path.is_symlink():
        raise ValueError("symlink_publication_refused")
    parent = os.stat(str(path.parent))
    fd, temporary = tempfile.mkstemp(prefix=".publish-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fchmod(stream.fileno(), mode)
            if os.fstat(stream.fileno()).st_gid != parent.st_gid:
                os.fchown(stream.fileno(), -1, parent.st_gid)
            os.fsync(stream.fileno())
        os.replace(temporary, str(path))
        _fsync_directory(path.parent)
    finally:
        if os.path.lexists(temporary):
            os.unlink(temporary)


def load_command_key(path=None, *, environ=None):
    """Read the C15 key: absolute, no symlink, one link, owner euid, 0400/0600, 32..16384 B."""
    environ = os.environ if environ is None else environ
    value = path if path is not None else environ.get(COMMAND_KEY_ENV, "")
    if not value:
        raise ValueError("lab_command_key_unconfigured")
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("lab_command_key_path_not_absolute")
    try:
        fd = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        raise ValueError("lab_command_key_unavailable") from None
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) not in (0o400, 0o600)
                or not MIN_KEY_BYTES <= info.st_size <= MAX_KEY_BYTES):
            raise ValueError("lab_command_key_file_unprotected")
        chunks = []
        remaining = MAX_KEY_BYTES + 1
        while remaining > 0:
            part = os.read(fd, remaining)
            if not part:
                break
            chunks.append(part)
            remaining -= len(part)
        data = b"".join(chunks)
    finally:
        os.close(fd)
    if data.endswith(b"\n"):
        data = data[:-1]
    if not MIN_KEY_BYTES <= len(data) <= MAX_KEY_BYTES or any(byte in data for byte in b"\x00\r\n"):
        raise ValueError("lab_command_key_invalid")
    return data


def _require_key(key):
    if type(key) is not bytes or not MIN_KEY_BYTES <= len(key) <= MAX_KEY_BYTES:
        raise ValueError("lab_command_key_invalid")


def command_mac(key, envelope):
    """HMAC-SHA256 over the canonical envelope without its MAC field (C15)."""
    _require_key(key)
    if not isinstance(envelope, dict) or COMMAND_MAC_FIELD in envelope:
        raise ValueError("unsigned_command_envelope_required")
    return hmac.new(key, canonical(envelope), hashlib.sha256).hexdigest()


def sign_command(key, envelope):
    return {**envelope, COMMAND_MAC_FIELD: command_mac(key, envelope)}


def verify_command(key, envelope):
    """Return the envelope without its MAC; missing or invalid MACs are rejected."""
    if not isinstance(envelope, dict):
        raise ValueError("command_envelope_object_required")
    mac = envelope.get(COMMAND_MAC_FIELD)
    if type(mac) is not str or not _HEX64.fullmatch(mac):
        raise ValueError("command_mac_missing")
    unsigned = {name: value for name, value in envelope.items() if name != COMMAND_MAC_FIELD}
    if not hmac.compare_digest(command_mac(key, unsigned), mac):
        raise ValueError("command_mac_invalid")
    return unsigned

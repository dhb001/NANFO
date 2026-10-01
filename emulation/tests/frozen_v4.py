"""Tracked frozen v4 lab source for tests (ADR-028); not a test module.

The ignored private copy ``ai-engine/artifacts/adr024-qualified-001/recovery/emulation`` is
byte-identical to the members of the tracked archive ``emulation/frozen/adr015-prechange-
v4-source.tar.gz``. Tests extract that archive once, after checking it against both the
recorded pin below and ``emulation/frozen/SHA256SUMS``, into a private temporary
directory removed at interpreter exit. The archive itself is never modified.
"""

import atexit
import hashlib
import io
import shutil
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ARCHIVE = ROOT / "emulation/frozen/adr015-prechange-v4-source.tar.gz"
SUMS = ROOT / "emulation/frozen/SHA256SUMS"
ARCHIVE_SHA256 = "444663dc3a7223044a9e8830ba5dd24cd3e1b041c60dc278e4bba56eb7252384"
_EXTRACTED = []


def available():
    return ARCHIVE.is_file() and SUMS.is_file()


def frozen_emulation():
    """Directory holding the frozen v4 ``emulation`` package (extracted once per process)."""
    if _EXTRACTED:
        return _EXTRACTED[0]
    data = ARCHIVE.read_bytes()
    recorded = {name: value for value, name in (line.split() for line in SUMS.read_text().splitlines()
                                                 if line.strip())}
    digest = hashlib.sha256(data).hexdigest()
    if digest != ARCHIVE_SHA256 or recorded.get(ARCHIVE.name) != ARCHIVE_SHA256:
        raise AssertionError("tracked frozen v4 archive does not match its recorded SHA-256")
    root = Path(tempfile.mkdtemp(prefix="nanfo-frozen-v4-"))
    atexit.register(shutil.rmtree, root, True)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        archive.extractall(root, filter="data")
    _EXTRACTED.append(root / "emulation")
    return _EXTRACTED[0]

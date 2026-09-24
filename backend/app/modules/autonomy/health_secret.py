"""Descriptor-bound confidential key reads, separate from public evidence policy.

ADR-028 C21: receiver-health receipts are signed with Ed25519 by the receiver
(``NANFO_RECEIVER_HEALTH_PRIVATE_KEY_FILE``) and verified with the public key only
(``NANFO_RECEIVER_HEALTH_PUBLIC_KEY_FILE``); PEM files, mode 0400/0600. The legacy
shared HMAC secret is read only when ``NANFO_RECEIVER_HEALTH_LEGACY_HMAC=true``
(frozen runtimes), so an ordinary verifier can no longer forge receipts.
"""

import hashlib
import os
import stat
from pathlib import Path, PurePosixPath

PRIVATE_KEY_ENV = "NANFO_RECEIVER_HEALTH_PRIVATE_KEY_FILE"
PUBLIC_KEY_ENV = "NANFO_RECEIVER_HEALTH_PUBLIC_KEY_FILE"
LEGACY_HMAC_ENV = "NANFO_RECEIVER_HEALTH_LEGACY_HMAC"
KEY_FILE_MODES = frozenset({0o400, 0o600})


def legacy_hmac_enabled() -> bool:
    return os.environ.get(LEGACY_HMAC_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def _protected_directory(info) -> bool:
    sticky_root = info.st_uid == 0 and bool(info.st_mode & stat.S_ISVTX)
    return info.st_uid in {0, os.geteuid()} and not (info.st_mode & 0o022 and not sticky_root)


def read_health_secret(root, reference):
    root = Path(root)
    relative = PurePosixPath(reference.path)
    if (not root.is_absolute() or ".." in root.parts or not reference.path
            or relative.is_absolute() or str(relative) != reference.path
            or any(p in {"", ".", ".."} for p in reference.path.split("/"))):
        raise ValueError("health_secret_path_invalid")
    descriptors = []
    try:
        fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        descriptors.append(fd)
        for component in (*root.parts[1:], *relative.parts[:-1]):
            fd = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            descriptors.append(fd)
            if not _protected_directory(os.fstat(fd)):
                raise ValueError("health_secret_ancestor_unprotected")
        fd = os.open(relative.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        descriptors.append(fd)
        before = os.fstat(fd)
        def private(info):
            return (stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600
                    and info.st_uid in {0, os.geteuid()} and info.st_nlink == 1
                    and 32 <= info.st_size <= 4096)
        if not private(before) or before.st_size != reference.size_bytes:
            raise ValueError("health_secret_requires_private_0600")
        with os.fdopen(os.dup(fd), "rb") as stream:
            content = stream.read(4097)
        after = os.fstat(fd)
        if (not private(after) or (before.st_size, before.st_mtime_ns, before.st_ctime_ns) !=
                (after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                or len(content) != before.st_size or hashlib.sha256(content).hexdigest() != reference.sha256):
            raise ValueError("health_secret_changed_or_hash_mismatch")
        # Recheck permissions on the opened ancestry, not a later pathname target.
        for directory in descriptors[:-1]:
            if not _protected_directory(os.fstat(directory)):
                raise ValueError("health_secret_ancestor_unprotected")
        return content
    except OSError as exc:
        raise ValueError("health_secret_unreadable_or_symlink") from exc
    finally:
        for fd in reversed(descriptors):
            os.close(fd)


def read_key_file(path, *, max_size=4096) -> bytes:
    """Read an absolute operator key file: no symlinks, protected ancestry, 0400/0600, one link."""
    path = Path(str(path)) if path else None
    if path is None or not path.is_absolute() or any(part in {"..", "."} for part in path.parts) or path.name in {"", "/"}:
        raise ValueError("receiver_health_key_path_invalid")
    descriptors = []
    try:
        fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        descriptors.append(fd)
        for component in path.parts[1:-1]:
            fd = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            descriptors.append(fd)
            if not _protected_directory(os.fstat(fd)):
                raise ValueError("receiver_health_key_ancestor_unprotected")
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        descriptors.append(fd)
        before = os.fstat(fd)
        def private(info):
            return (stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) in KEY_FILE_MODES
                    and info.st_uid in {0, os.geteuid()} and info.st_nlink == 1 and 0 < info.st_size <= max_size)
        if not private(before):
            raise ValueError("receiver_health_key_requires_0400_or_0600")
        with os.fdopen(os.dup(fd), "rb") as stream:
            content = stream.read(max_size + 1)
        after = os.fstat(fd)
        if (not private(after) or (before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                != (after.st_size, after.st_mtime_ns, after.st_ctime_ns) or len(content) != before.st_size):
            raise ValueError("receiver_health_key_changed_during_read")
        for directory in descriptors[:-1]:
            if not _protected_directory(os.fstat(directory)):
                raise ValueError("receiver_health_key_ancestor_unprotected")
        return content
    except OSError as exc:
        raise ValueError("receiver_health_key_unreadable_or_symlink") from exc
    finally:
        for fd in reversed(descriptors):
            os.close(fd)


def key_id_for(public_key) -> str:
    """C21 key id: first 16 hex characters of SHA-256 over the raw 32-byte public key."""
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    return hashlib.sha256(public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)).hexdigest()[:16]


class ReceiptSigner:
    """Receiver-side Ed25519 signing identity (private key never leaves the receiver)."""

    def __init__(self, private_key):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        if not isinstance(private_key, Ed25519PrivateKey):
            raise ValueError("receiver_health_key_not_ed25519")
        self._key = private_key
        self.key_id = key_id_for(private_key.public_key())

    def sign(self, data: bytes) -> str:
        return self._key.sign(data).hex()


class ReceiptVerifier:
    """Verifier-side identity: holds only the public key, so it cannot mint receipts."""

    def __init__(self, public_key):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        if not isinstance(public_key, Ed25519PublicKey):
            raise ValueError("receiver_health_key_not_ed25519")
        self._key = public_key
        self.key_id = key_id_for(public_key)

    def verify(self, data: bytes, signature: str) -> bool:
        from cryptography.exceptions import InvalidSignature

        if not isinstance(signature, str) or len(signature) != 128:
            return False
        try:
            self._key.verify(bytes.fromhex(signature), data)
        except (InvalidSignature, ValueError):
            return False
        return True


def load_signing_key(path) -> ReceiptSigner:
    from cryptography.hazmat.primitives.serialization import load_pem_private_key

    try:
        key = load_pem_private_key(read_key_file(path), password=None)
    except (TypeError, ValueError) as exc:
        raise ValueError("receiver_health_private_key_invalid") from exc
    return ReceiptSigner(key)


def load_verify_key(path) -> ReceiptVerifier:
    from cryptography.hazmat.primitives.serialization import load_pem_public_key

    try:
        key = load_pem_public_key(read_key_file(path))
    except (TypeError, ValueError) as exc:
        raise ValueError("receiver_health_public_key_invalid") from exc
    return ReceiptVerifier(key)


def receipt_credentials(legacy_key=None):
    """Verifier credentials (API/autonomy worker): Ed25519 public key, legacy HMAC only if enabled."""
    path = os.environ.get(PUBLIC_KEY_ENV)
    verifier = load_verify_key(path) if path else None
    legacy = legacy_key if legacy_hmac_enabled() and legacy_key else None
    if verifier is None and legacy is None:
        raise ValueError("receiver_health_verifier_unconfigured")
    return verifier, legacy


def signing_credentials(legacy_key=None):
    """Receiver credentials: Ed25519 private key, legacy HMAC publication only if enabled."""
    path = os.environ.get(PRIVATE_KEY_ENV)
    signer = load_signing_key(path) if path else None
    legacy = legacy_key if legacy_hmac_enabled() and legacy_key else None
    if signer is None and legacy is None:
        raise ValueError("receiver_health_signing_key_unconfigured")
    return signer, legacy

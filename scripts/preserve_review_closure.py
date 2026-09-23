"""Offline ADR027 receipts: exact pinned export, portable verification, private copy.

Uses evidence_hygiene without fixture exemptions. No service/model operations;
originals are never changed. Public plans admit JSON/text/XML receipts only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile

import evidence_hygiene as hygiene

safe = hygiene.safe
MAX_FILE = 16 * 1024**2
MAX_TOTAL = 4 * MAX_FILE


def load(path):
    return safe.parse_json(hygiene.read_file(path.parent, path.name, MAX_FILE))


def public_name(name):
    hygiene.path_name(name)
    safe.require(hygiene.export_allowed(name) and Path(name).suffix in {".json", ".txt", ".xml"}
                 and name not in {"manifest.json", "selection.json", "SHA256SUMS"}, "receipt_path_required")
    return name


def export(plan, destination, known_tokens=()):
    """Preflight every original, then use the existing exact-byte screened exporter."""
    safe.require(isinstance(plan, dict) and set(plan) == {"schema", "files"}
                 and plan["schema"] == "nanfo-review-closure-selection-v1"
                 and isinstance(plan["files"], dict) and 0 < len(plan["files"]) <= 100,
                 "invalid_selection")
    scanner = hygiene.Scanner(known_tokens=known_tokens, export_mode=True)
    payloads = {}
    for name, item in plan["files"].items():
        public_name(name)
        safe.require(isinstance(item, dict) and set(item) == {"source", "sha256", "bytes"}, "invalid_pin")
        source = Path(item["source"])
        safe.require(source.is_absolute() and hygiene.export_allowed(source.name), "invalid_source")
        data = hygiene.read_file(source.parent, source.name, MAX_FILE)
        safe.require(safe.descriptor(data) == {k: item[k] for k in ("bytes", "sha256")}, "source_pin_mismatch")
        scanner.inspect(name, data)
        safe.require(not scanner.findings, "receipt_screening_failed")
        payloads[name] = data
    safe.require(sum(map(len, payloads.values())) <= MAX_TOTAL, "bundle_byte_limit")
    selection = safe.canonical(plan)
    scanner.inspect("selection.json", selection)
    safe.require(not scanner.findings, "selection_screening_failed")
    payloads["selection.json"] = selection
    # Staging is private and bounded. Export handles no-clobber and fsync/readback.
    with tempfile.TemporaryDirectory(prefix="review-closure-") as directory:
        stage = Path(directory)
        for name, data in payloads.items():
            hygiene.publish(stage, name, data)
        allowlist = {"schema": hygiene.ALLOWLIST_SCHEMA,
                     "files": {n: safe.descriptor(d) for n, d in payloads.items()}}
        result = hygiene.export_evidence(stage, destination, allowlist, known_tokens=known_tokens)
    checksum_files = [*payloads, "manifest.json"]
    sums = "".join(f"{safe.sha256(hygiene.read_file(destination, n, MAX_FILE))}  {n}\n"
                   for n in sorted(checksum_files)).encode()
    hygiene.publish(destination, "SHA256SUMS", sums)
    return {**result, "evidence_files": len(plan["files"]), "checksums_sha256": safe.sha256(sums)}


def verify(destination, known_tokens=()):
    """Does not access original sources; exact inventory, hashes and scanner all gate."""
    manifest = load(destination / "manifest.json")
    safe.require(manifest.get("schema") == hygiene.EXPORT_SCHEMA, "invalid_manifest")
    inventory = hygiene.names(destination, 1000)
    safe.require(set(inventory) == set(manifest["files"]) | {"manifest.json", "SHA256SUMS"},
                 "bundle_inventory_mismatch")
    for name, pin in manifest["files"].items():
        safe.require(safe.descriptor(hygiene.read_file(destination, name, MAX_FILE)) == pin,
                     "bundle_digest_mismatch")
    expected = "".join(f"{safe.sha256(hygiene.read_file(destination, n, MAX_FILE))}  {n}\n"
                       for n in sorted(set(inventory) - {"SHA256SUMS"})).encode()
    safe.require(hygiene.read_file(destination, "SHA256SUMS", MAX_FILE) == expected,
                 "checksums_mismatch")
    plan = load(destination / "selection.json")
    safe.require(set(plan["files"]) == set(manifest["files"]) - {"selection.json"}, "selection_mismatch")
    for name, item in plan["files"].items():
        safe.require(manifest["files"][name] == {k: item[k] for k in ("bytes", "sha256")}, "selection_pin_mismatch")
    result = hygiene.Scanner(known_tokens=known_tokens, export_mode=True).scan(destination, inventory)
    safe.require(not result["findings"], "bundle_screening_failed")
    return {**result, "evidence_files": len(plan["files"]),
            "manifest_sha256": safe.sha256(hygiene.read_file(destination, "manifest.json", MAX_FILE)),
            "checksums_sha256": safe.sha256(expected)}


def compare(repository, manifest):
    """Only compare listed paths; absence of additional-file inventory is explicit."""
    safe.require(isinstance(manifest, dict) and 0 < len(manifest) <= 20000, "invalid_source_manifest")
    changed, missing = {}, []
    for name, expected in manifest.items():
        hygiene.path_name(name)
        safe.require(isinstance(expected, str) and safe.HEX.fullmatch(expected), "invalid_source_digest")
        try:
            actual = safe.sha256(hygiene.read_file(repository, name, MAX_FILE))
        except FileNotFoundError:
            missing.append(name)
            continue
        if actual != expected:
            changed[name] = {"accepted_sha256": expected, "observed_sha256": actual}
    return {"listed_files": len(manifest), "matched": len(manifest) - len(changed) - len(missing),
            "changed": changed, "missing": missing, "additional_paths_examined": False}


def copy_private(source, destination, *, max_bytes):
    """Stream an immutable private regular file to an exclusive 0600 destination."""
    with safe.directory_fd(source.parent) as parent:
        fd = os.open(source.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    with os.fdopen(fd, "rb") as stream, safe.directory_fd(destination.parent) as parent:
        before = os.fstat(stream.fileno())
        info = os.fstat(parent)
        safe.require(info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o700,
                     "unsafe_private_destination")
        safe.require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                     and before.st_uid == os.geteuid() and stat.S_IMODE(before.st_mode) == 0o600
                     and before.st_size <= max_bytes, "unsafe_private_source")
        fd = os.open(destination.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=parent)
        digest = hashlib.sha256()
        size = 0
        with os.fdopen(fd, "wb") as target:
            while chunk := stream.read(1024**2):
                size += len(chunk)
                safe.require(size <= max_bytes, "private_copy_limit")
                digest.update(chunk)
                target.write(chunk)
            target.flush()
            os.fsync(target.fileno())
        os.fsync(parent)
        after = os.fstat(stream.fileno())
        safe.require((before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
                     (size, after.st_mtime_ns, after.st_ctime_ns), "private_source_changed")
        fd = os.open(destination.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
        with os.fdopen(fd, "rb") as copied:
            safe.require(hashlib.file_digest(copied, "sha256").hexdigest() == digest.hexdigest(),
                         "private_copy_mismatch")
    return {"bytes": size, "sha256": digest.hexdigest()}


def preserve_backup(repository, source, destination, key_file, key_destination):
    """Copy an authenticated encrypted backup and separately copy its temporary key.

    Existing backup_restore authenticates the manifest and ciphertext. Original key,
    archives and external secret mounts stay in place. No plaintext archive export.
    """
    import backup_restore

    artifacts = (repository / "ai-engine/artifacts").absolute()
    source, destination = source.absolute(), destination.absolute()
    key_destination = key_destination.absolute()
    safe.require(destination.parent == artifacts and key_destination.parent == artifacts
                 and destination != key_destination and not key_file.absolute().is_relative_to(source),
                 "separate_artifact_roots_required")
    for path in (destination, key_destination):
        safe.require(not path.exists() and not path.is_symlink(), "private_output_exists")
        result = subprocess.run(["git", "-C", str(repository), "check-ignore", "-q", str(path / "receipt.json")],
                                capture_output=True, check=False)
        safe.require(result.returncode == 0, "private_output_not_ignored")
    with safe.directory_fd(key_file.parent):
        with backup_restore.protected_file(key_file, size=32) as stream:
            key = stream.read()
    try:
        manifest = backup_restore.load_manifest(source, key)
    except backup_restore.OperationError:
        raise safe.EvidenceError("backup_authentication_failed") from None
    selected = {"manifest.json", "manifest.hmac"} | {
        item["file"] for item in manifest["volumes"] + manifest.get("binds", [])}
    safe.require(set(hygiene.names(source, 100)) == selected, "backup_inventory_mismatch")
    hygiene.mkdir_private(destination, exclusive=True)
    hygiene.mkdir_private(key_destination, exclusive=True)
    pins = {}
    for name in sorted(selected):
        safe.require(name in {"manifest.json", "manifest.hmac"}
                     or re.fullmatch(r"volume-[0-9]{4}\.tar\.gcm", name), "invalid_archive_name")
        pins[name] = copy_private(source / name, destination / name, max_bytes=100 * 1024**3)
    copy_private(key_file, key_destination / "backup.key", max_bytes=32)
    with backup_restore.protected_file(key_destination / "backup.key", size=32) as stream:
        safe.require(stream.read() == key, "key_copy_mismatch")
    try:
        safe.require(backup_restore.load_manifest(destination, key) == manifest, "backup_copy_mismatch")
    except backup_restore.OperationError:
        raise safe.EvidenceError("backup_authentication_failed") from None
    receipt = {"schema": "nanfo-review-backup-preservation-v1", "status": "passed",
               "source": str(source), "destination": str(destination),
               "separate_key_directory": str(key_destination), "originals_retained": True,
               "manifest_hmac_and_ciphertext_verified": True, "files": pins,
               "volumes": len(manifest["volumes"]), "binds": len(manifest.get("binds", [])),
               "off_host_escrow": False, "external_secret_mounts_copied": False}
    hygiene.publish(destination, "preservation-receipt.json", safe.canonical(receipt))
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("export", "verify", "compare", "backup"))
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--known-private", type=Path)
    parser.add_argument("--repository", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--source", type=Path)
    parser.add_argument("--key-file", type=Path)
    parser.add_argument("--key-destination", type=Path)
    args = parser.parse_args()
    try:
        tokens = hygiene.known_private_tokens(args.known_private) if args.known_private else ()
        if args.operation == "export":
            result = export(load(args.plan), args.destination, tokens)
        elif args.operation == "verify":
            result = verify(args.destination, tokens)
        elif args.operation == "compare":
            result = compare(args.repository, load(args.source))
        else:
            result = preserve_backup(args.repository, args.source, args.destination,
                                     args.key_file, args.key_destination)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (safe.EvidenceError, OSError, ValueError, KeyError, TypeError, AttributeError):
        print(json.dumps({"status": "failed", "rule": "preservation_refused"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

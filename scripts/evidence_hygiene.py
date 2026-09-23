"""ADR027 offline evidence hygiene; no service operations or Git history changes.

scan is a failing gate, including extensionless files and nested ZIP/TAR/gzip/bzip2/
xz containers detected by bytes. Export selects exact hash-pinned files, never a
directory glob; sanitization means omission/refusal, never rewriting raw evidence.
Diagnostics contain rule codes and path hashes only, never matched values/names.
"""

from __future__ import annotations

import argparse
import ast
import bz2
import gzip
import io
import json
import lzma
import os
import re
import stat
import subprocess
import sys
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy"))
import release_manifest as safe

Error = safe.EvidenceError
CAMPAIGN = "nanfo-experimental-campaign-014"
MANIFEST = "manifest.json"
PRIVATE_SCHEMA = "nanfo-private-evidence-v1"
EXPORT_SCHEMA = "nanfo-sanitized-evidence-v1"
ALLOWLIST_SCHEMA = "nanfo-evidence-allowlist-v1"
FIXTURE_SCHEMA = "nanfo-synthetic-fixtures-v1"
# Scan exemptions are explicit caller-supplied policy, never implicit test-directory
# skips. CI uses security/evidence-fixtures.v1.json; export accepts no exemptions.
TOKEN_NAME = re.compile(r"(?:receiver[-_]token|access[-_]token|refresh[-_]token|api[-_]key)(?:\.[a-z0-9]+)?$", re.I)
SECRET_KEY = re.compile(
    r"(?:[a-z0-9]+[_-])*(?:password|passwd|secret|secret_key|signing_key|private_key|"
    r"api_key|access_token|refresh_token|receiver_token|admission_token|token|credentials)", re.I
)
ASSIGNMENT = re.compile(
    rb'''(?i)(?<![a-z0-9_/])(?:[a-z0-9]+[_-])*(?:password|passwd|secret|secret_key|signing_key|private_key|api_key|access_token|refresh_token|receiver_token|admission_token|token)["']?[ \t]*[=:][ \t]*["']?([a-z0-9_./+~=-]{16,})'''
)
BEARER = re.compile(rb"(?i)\bBearer\s+([a-z0-9_.~+/-]{16,})")
JWT = re.compile(rb"\beyJ[a-zA-Z0-9_-]{8,}\.[a-zA-Z0-9_-]{8,}\.[a-zA-Z0-9_-]{8,}")
PRIVATE_KEY = re.compile(rb"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----")
DSN = re.compile(rb"(?<![a-z0-9])[a-z][a-z0-9+.-]{0,31}://[^\s/:{}]+:([^\s/@{}]+)@", re.I)


def require(ok, code):
    safe.require(ok, code)


def path_name(name):
    """Canonical relative names, also for archives; never interpret a member path."""
    require(isinstance(name, str) and 0 < len(name) <= 1024, "invalid_path")
    parts = PurePosixPath(name).parts
    require(not re.search(r"[\\\x00-\x1f\x7f:]", name) and not name.startswith("/")
            and str(PurePosixPath(name)) == name
            and all(part not in (".", "..") for part in parts), "unsafe_path")
    return name


def read_file(root, name, limit):
    """Descriptor-relative reads reject ancestor links, hardlinks and special files."""
    path_name(name)
    path = root / name
    with safe.directory_fd(path.parent) as parent:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        with os.fdopen(fd, "rb") as stream:
            before = os.fstat(stream.fileno())
            require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1, "unsafe_file")
            require(before.st_size <= limit, "file_byte_limit")
            data = stream.read(limit + 1)
            after = os.fstat(stream.fileno())
            require(len(data) == before.st_size <= limit and
                    (before.st_mtime_ns, before.st_ctime_ns) ==
                    (after.st_mtime_ns, after.st_ctime_ns), "file_changed")
            return data


def names(root, maximum):
    result = []
    visited = 0

    def walk(fd, prefix):
        nonlocal visited
        with os.scandir(fd) as entries:
            for entry in entries:
                visited += 1
                require(visited <= maximum, "entry_limit")
                name = prefix + entry.name
                path_name(name)
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISDIR(info.st_mode):
                    require(len(PurePosixPath(name).parts) <= 64, "directory_depth_limit")
                    child = os.open(entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                    try:
                        walk(child, name + "/")
                    finally:
                        os.close(child)
                else:
                    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "unsafe_file")
                    result.append(name)
                    require(len(result) <= maximum, "file_count_limit")

    with safe.directory_fd(root) as fd:
        walk(fd, "")
    return sorted(result)


def tracked_names(root, *, include_untracked=False):
    command = ["git", "-C", str(root), "ls-files", "-z"]
    if include_untracked:
        command.extend(["--cached", "--others", "--exclude-standard"])
    result = subprocess.run(command,
                            capture_output=True, check=False)
    require(result.returncode == 0, "git_inventory_failed")
    return [path_name(n) for n in result.stdout.decode().split("\0") if n]


def synthetic(value):
    """Only unmistakable literals; no entropy heuristic or blanket test-directory skip."""
    if not isinstance(value, str):
        return False
    return value.lower() in {"", "redacted", "[redacted]", "change_me", "changeme",
                             "example", "placeholder", "test", "test-token", "test-password"}


@dataclass(frozen=True)
class Limits:
    file_bytes: int = 64 * 1024**2
    total_bytes: int = 4 * 1024**3
    entries: int = 50000
    depth: int = 5
    ratio: int = 200

    def __post_init__(self):
        require(all(type(v) is int and v > 0 for v in vars(self).values()), "invalid_limits")


class Scanner:
    def __init__(self, limits=None, known_tokens=(), fixtures=None, *, export_mode=False):
        self.limits = limits or Limits()
        self.known_tokens = tuple(known_tokens)
        require(all(isinstance(t, bytes) and len(t) >= 16 for t in self.known_tokens), "invalid_known_token")
        self.known_pattern = re.compile(b"|".join(re.escape(t) for t in self.known_tokens)) if self.known_tokens else None
        self.fixtures = fixtures or {}
        self.export_mode = export_mode
        self.findings = []
        self.total = 0
        self.entries = 0
        self.fixture_matches = 0

    def finding(self, name, rule):
        row = {"path_sha256": safe.sha256(name.encode()), "rule": rule}
        if row not in self.findings:
            self.findings.append(row)

    def charge(self, size):
        self.entries += 1
        self.total += size
        require(size <= self.limits.file_bytes, "file_byte_limit")
        require(self.entries <= self.limits.entries, "entry_limit")
        require(self.total <= self.limits.total_bytes, "total_byte_limit")

    def content_rules(self, data, *, python_source=False):
        rules = set()
        if self.known_pattern and self.known_pattern.search(data):
            rules.add("known_receiver_token")
        if PRIVATE_KEY.search(data):
            rules.add("private_key")
        if JWT.search(data):
            rules.add("jwt")
        for pattern, rule in ((ASSIGNMENT, "secret_assignment"), (BEARER, "bearer"), (DSN, "credential_url")):
            matches = list(pattern.finditer(data))
            if python_source and pattern is ASSIGNMENT and matches:
                # A Python variable/attribute assignment is not a credential literal.
                # Constant strings (including embedded config/JSON) remain screened.
                tree = ast.parse(data)
                literal_data = b"\n".join(node.value.encode() if isinstance(node.value, str) else node.value
                                          for node in ast.walk(tree) if isinstance(node, ast.Constant)
                                          and isinstance(node.value, (str, bytes)))
                matches = [m for m in matches if m.group(1) in literal_data]
            if any(not synthetic(m.group(1).decode("ascii")) for m in matches):
                rules.add(rule)
        return rules

    def json_rules(self, value, rules, depth=0):
        require(depth <= 64, "json_depth_limit")
        if isinstance(value, dict):
            for key, child in value.items():
                if SECRET_KEY.fullmatch(key) and child not in (None, False, "", [], {}):
                    if not synthetic(child):
                        rules.add("secret_field")
                self.json_rules(child, rules, depth + 1)
        elif isinstance(value, list):
            for child in value:
                self.json_rules(child, rules, depth + 1)
        elif isinstance(value, str):
            rules.update(self.content_rules(value.encode()))
            if value.lstrip().startswith(("{", "[")):
                try:
                    embedded = safe.parse_json(value.encode())
                except Error:
                    return
                self.json_rules(embedded, rules, depth + 1)

    def inspect(self, name, data, depth=0):
        """Never extract archives to disk; failures are findings, not silent exclusions."""
        try:
            self._inspect(name, data, depth)
        except Error as exc:
            # Only internal constant codes are accepted as diagnostics.
            code = str(exc)
            self.finding(name, code if re.fullmatch(r"[a-z_]+", code) else "invalid_content")
        except (OSError, ValueError, UnicodeError, RecursionError, EOFError, lzma.LZMAError,
                RuntimeError, NotImplementedError, SyntaxError, zipfile.BadZipFile, tarfile.TarError):
            self.finding(name, "uninspectable_content")

    def _inspect(self, name, data, depth):
        self.charge(len(data))
        require(depth <= self.limits.depth, "archive_depth_limit")
        if self.export_mode:
            require(all(export_allowed(part) for part in name.split("!/")), "private_export_path")
        rules = self.content_rules(data, python_source=name.endswith(".py"))
        rules.update(self.content_rules(name.encode()))
        if TOKEN_NAME.fullmatch(PurePosixPath(name).name) and data.strip():
            rules.add("credential_file")
        # Do not treat source-code examples as deployed JSON credentials.
        if name.lower().endswith((".json", ".jsonl", ".ndjson")):
            records = data.splitlines() if name.lower().endswith((".jsonl", ".ndjson")) else [data]
            for record in records:
                if record.strip():
                    self.json_rules(safe.parse_json(record), rules)
        fixture = self.fixtures.get(name)
        if fixture and safe.sha256(data) == fixture["sha256"]:
            # Exact, reviewed synthetic fixtures cannot hide a known compromised token.
            rules -= set(fixture["rules"]) - {"known_receiver_token", "credential_file"}
            self.fixture_matches += 1
        for rule in sorted(rules):
            self.finding(name, rule)

        lower = name.lower()
        if data.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")) or zipfile.is_zipfile(io.BytesIO(data)):
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                require(len(archive.infolist()) + self.entries <= self.limits.entries, "entry_limit")
                seen = set()
                for item in archive.infolist():
                    member = path_name(item.filename.rstrip("/") if item.is_dir() else item.filename)
                    require(member not in seen, "duplicate_archive_member")
                    seen.add(member)
                    mode = item.external_attr >> 16
                    require(not stat.S_IFMT(mode) or stat.S_ISREG(mode) or stat.S_ISDIR(mode), "archive_special_file")
                    require(not item.flag_bits & 1, "encrypted_archive")
                    require(item.file_size <= self.limits.file_bytes, "file_byte_limit")
                    require(item.file_size <= max(item.compress_size, 1) * self.limits.ratio, "archive_ratio_limit")
                    if item.is_dir():
                        self.charge(0)
                        continue
                    require(self.total + item.file_size <= self.limits.total_bytes, "total_byte_limit")
                    with archive.open(item) as stream:
                        payload = stream.read(self.limits.file_bytes + 1)
                    require(len(payload) == item.file_size, "archive_size_mismatch")
                    self.inspect(name + "!/" + member, payload, depth + 1)
            return
        codecs = ((b"\x1f\x8b", gzip.open), (b"BZh", bz2.BZ2File), (b"\xfd7zXZ\x00", None))
        for magic, codec in codecs:
            if data.startswith(magic):
                cap = min(self.limits.file_bytes, self.limits.total_bytes - self.total,
                          max(len(data), 1) * self.limits.ratio)
                require(cap > 0, "total_byte_limit")
                if codec is None:
                    decoder = lzma.LZMADecompressor(memlimit=64 * 1024**2)
                    payload = decoder.decompress(data, max_length=cap + 1)
                    require(decoder.eof and not decoder.unused_data, "unsupported_xz_stream")
                else:
                    with codec(io.BytesIO(data), "rb") as stream:
                        payload = stream.read(cap + 1)
                require(len(payload) <= cap, "decompression_limit")
                # Preserve the underlying suffix to parse compressed JSON as well.
                member = PurePosixPath(name).name
                member = re.sub(r"\.(?:gz|bz2|xz)$", "", member)
                if member == PurePosixPath(name).name:
                    member = "payload"
                self.inspect(name + "!/" + member, payload, depth + 1)
                return
        # TAR magic is not mandatory for old-format headers; tarfile validates checksums.
        is_tar = len(data) >= 512 and (data[257:262] == b"ustar" or tarfile.is_tarfile(io.BytesIO(data)))
        if is_tar:
            seen = set()
            with tarfile.open(fileobj=io.BytesIO(data), mode="r|") as archive:
                for item in archive:
                    member = path_name(item.name.rstrip("/") if item.isdir() else item.name)
                    require(member not in seen, "duplicate_archive_member")
                    seen.add(member)
                    require(len(seen) + self.entries <= self.limits.entries, "entry_limit")
                    require(item.isfile() or item.isdir(), "archive_special_file")
                    require(not item.sparse, "sparse_archive")
                    if item.isdir():
                        self.charge(0)
                        continue
                    require(item.size <= self.limits.file_bytes, "file_byte_limit")
                    require(self.total + item.size <= self.limits.total_bytes, "total_byte_limit")
                    with archive.extractfile(item) as stream:
                        payload = stream.read(self.limits.file_bytes + 1)
                    require(len(payload) == item.size, "archive_size_mismatch")
                    self.inspect(name + "!/" + member, payload, depth + 1)
            return
        require(not (lower.endswith((".zip", ".tar", ".tgz", ".gz", ".bz2", ".xz", ".7z", ".rar", ".zst", ".lz4"))
                     or data.startswith((b"7z\xbc\xaf\x27\x1c", b"Rar!", b"\x28\xb5\x2f\xfd", b"\x04\x22\x4d\x18"))),
                "unsupported_or_invalid_archive")

    def scan(self, root, selected):
        require(len(selected) <= self.limits.entries, "entry_limit")
        for name in selected:
            if self.total >= self.limits.total_bytes or self.entries >= self.limits.entries:
                self.finding(name, "scan_budget_exhausted")
                break
            try:
                data = read_file(root, name, self.limits.file_bytes)
                self.inspect(name, data)
            except (Error, OSError):
                self.finding(name, "unreadable_or_unsafe_file")
        return self.report()

    def report(self):
        return {"status": "failed" if self.findings else "passed", "entries": self.entries,
                "inspected_bytes": self.total, "synthetic_fixture_matches": self.fixture_matches,
                "findings": self.findings}


def load_fixtures(path):
    value = safe.parse_json(read_file(path.parent, path.name, 1024**2))
    require(isinstance(value, dict) and set(value) == {"schema", "files"}
            and value["schema"] == FIXTURE_SCHEMA and isinstance(value["files"], dict), "invalid_fixture_manifest")
    for name, item in value["files"].items():
        # Archive members are pinned individually, never exempt an entire container.
        for part in name.split("!/"):
            path_name(part)
        require(isinstance(item, dict) and set(item) == {"sha256", "rules", "reason"}
                and isinstance(item["sha256"], str) and safe.HEX.fullmatch(item["sha256"])
                and isinstance(item["reason"], str) and len(item["reason"].strip()) >= 16
                and isinstance(item["rules"], list) and item["rules"]
                and all(isinstance(rule, str) for rule in item["rules"])
                and set(item["rules"]) <= {"secret_assignment", "secret_field", "credential_url", "bearer", "jwt", "private_key"},
                "invalid_fixture_exception")
    return value["files"]


def mkdir_private(path, exclusive=False):
    with safe.directory_fd(path.parent) as parent:
        info = os.fstat(parent)
        require(info.st_uid == os.geteuid() and not info.st_mode & 0o022, "unsafe_output_parent")
        try:
            os.mkdir(path.name, 0o700, dir_fd=parent)
            os.fsync(parent)
        except FileExistsError:
            require(not exclusive, "output_exists")
        fd = os.open(path.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        try:
            info = os.fstat(fd)
            require(info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o700, "unsafe_output_directory")
        finally:
            os.close(fd)


def publish(root, name, data):
    path_name(name)
    parent = root
    for part in PurePosixPath(name).parts[:-1]:
        parent /= part
        mkdir_private(parent)
    safe.publish(root / name, data)
    require(read_file(root, name, max(len(data), 1)) == data, "copy_verification_failed")


def new_destination(source, destination):
    source, destination = source.absolute(), destination.absolute()
    require(".." not in destination.parts and not destination.is_relative_to(source)
            and not source.is_relative_to(destination), "source_output_overlap")
    with safe.directory_fd(destination.parent):
        pass
    mkdir_private(destination, exclusive=True)
    return destination


def preserve_credentials(repository, destination, expected=71):
    """Preserve only tracked receiver-token files; never delete originals here."""
    selected = [n for n in tracked_names(repository)
                if n.startswith(CAMPAIGN + "/") and PurePosixPath(n).name == "receiver-token"]
    require(len(selected) == expected and expected > 0, "unexpected_credential_count")
    payloads = {n: read_file(repository, n, 4096) for n in selected}
    require(all(re.fullmatch(rb"[a-f0-9]{64}", d) for d in payloads.values()), "unexpected_credential_shape")
    # This command is intentionally confined to the existing ignored artifact store.
    destination = destination.absolute()
    artifacts = (repository / "ai-engine/artifacts").absolute()
    require(destination.parent == artifacts, "private_artifact_destination_required")
    result = subprocess.run(["git", "-C", str(repository), "check-ignore", "-q", str(destination / MANIFEST)],
                            capture_output=True, check=False)
    require(result.returncode == 0, "destination_not_gitignored")
    mkdir_private(destination, exclusive=True)
    manifest = {"schema": PRIVATE_SCHEMA, "files": {n: safe.descriptor(d) for n, d in payloads.items()}}
    for name, data in payloads.items():
        publish(destination, name, data)
    publish(destination, MANIFEST, safe.canonical(manifest))
    result = verify_private(destination, repository)
    publish(destination, "preservation-complete.json", safe.canonical(result))
    return result


def verify_private(destination, source=None):
    manifest = safe.parse_json(read_file(destination, MANIFEST, 1024**2))
    require(manifest["schema"] == PRIVATE_SCHEMA and manifest["files"], "invalid_private_manifest")
    require(set(names(destination, 10000)) - {MANIFEST, "preservation-complete.json", "campaign-scan-001.json"}
            == set(manifest["files"]), "private_inventory_mismatch")
    total = 0
    for name, descriptor in manifest["files"].items():
        data = read_file(destination, name, 4096)
        require(safe.descriptor(data) == descriptor, "private_digest_mismatch")
        if source is not None:
            require(read_file(source, name, 4096) == data, "source_copy_mismatch")
        total += len(data)
    for name in names(destination, 10000):
        path = destination / name
        require(path.stat().st_uid == os.geteuid() and stat.S_IMODE(path.stat().st_mode) == 0o600, "private_file_permissions")
        for parent in [path.parent, *path.parent.parents]:
            if not parent.is_relative_to(destination):
                break
            require(parent.stat().st_uid == os.geteuid() and stat.S_IMODE(parent.stat().st_mode) == 0o700, "private_directory_permissions")
    result = {"status": "passed", "files": len(manifest["files"]), "bytes": total,
            "manifest_sha256": safe.sha256(read_file(destination, MANIFEST, 1024**2)),
            "source_compared": source is not None}
    if (destination / "preservation-complete.json").exists():
        receipt = safe.parse_json(read_file(destination, "preservation-complete.json", 1024**2))
        require(receipt == {**result, "source_compared": True}, "private_receipt_mismatch")
    return result


def known_private_tokens(destination):
    verify_private(destination)
    manifest = safe.parse_json(read_file(destination, MANIFEST, 1024**2))
    return tuple(read_file(destination, n, 4096).strip() for n in manifest["files"])


def export_allowed(name):
    path_name(name)
    return not any(TOKEN_NAME.fullmatch(part) or part.startswith(".") or
                   re.search(r"(?:admission|credential|secret|private|(?:^|[-_])config(?:\.|$))", part, re.I)
                   or part.lower().endswith((".env", ".key", ".pem", ".p12", ".pfx"))
                   for part in PurePosixPath(name).parts)


def export_evidence(source, destination, allowlist, *, limits=None, known_tokens=()):
    """Exact allowlist + digest + screening. Any refusal happens before publication."""
    require(isinstance(allowlist, dict) and set(allowlist) == {"schema", "files"}
            and allowlist["schema"] == ALLOWLIST_SCHEMA and isinstance(allowlist["files"], dict)
            and allowlist["files"], "invalid_allowlist")
    # Export never accepts fixture exemptions, even the reviewed scan-only defaults.
    scanner = Scanner(limits, known_tokens, fixtures={}, export_mode=True)
    require(len(allowlist["files"]) <= scanner.limits.entries, "entry_limit")
    payloads = {}
    for name, descriptor in allowlist["files"].items():
        require(export_allowed(name) and name != MANIFEST, "private_export_path")
        require(isinstance(descriptor, dict) and set(descriptor) == {"sha256", "bytes"}, "invalid_descriptor")
        data = read_file(source, name, scanner.limits.file_bytes)
        require(safe.descriptor(data) == descriptor, "allowlist_digest_mismatch")
        scanner.inspect(name, data)
        require(not scanner.findings, "export_screening_failed")
        payloads[name] = data
    destination = new_destination(source, destination)
    for name, data in payloads.items():
        publish(destination, name, data)
    manifest = {"schema": EXPORT_SCHEMA, "files": {n: safe.descriptor(d) for n, d in payloads.items()},
                "sanitization": "explicit-selection-no-byte-rewriting"}
    publish(destination, MANIFEST, safe.canonical(manifest))
    return {"status": "passed", "files": len(payloads), "bytes": sum(map(len, payloads.values())),
            "manifest_sha256": safe.sha256(safe.canonical(manifest))}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("scan", "export", "preserve-credentials", "verify-private"))
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--allowlist", type=Path)
    parser.add_argument("--fixtures", type=Path)
    parser.add_argument("--known-private", type=Path)
    parser.add_argument("--tracked", action="store_true", help="Scan tracked working-tree files; pending deletions excluded")
    parser.add_argument("--include-untracked", action="store_true", help="With --tracked, include nonignored new files for precommit validation")
    parser.add_argument("--max-file-bytes", type=int, default=Limits.file_bytes)
    parser.add_argument("--max-total-bytes", type=int, default=Limits.total_bytes)
    parser.add_argument("--max-entries", type=int, default=Limits.entries)
    parser.add_argument("--max-depth", type=int, default=Limits.depth)
    parser.add_argument("--max-ratio", type=int, default=Limits.ratio)
    args = parser.parse_args(argv)
    try:
        limits = Limits(args.max_file_bytes, args.max_total_bytes, args.max_entries, args.max_depth, args.max_ratio)
        tokens = known_private_tokens(args.known_private) if args.known_private else ()
        if args.operation == "scan":
            require(not args.include_untracked or args.tracked, "tracked_required")
            selected = tracked_names(args.root, include_untracked=args.include_untracked) if args.tracked else names(args.root, limits.entries)
            if args.tracked:
                # git diff --diff-filter=D distinguishes intentional worktree deletions.
                result = subprocess.run(["git", "-C", str(args.root), "diff", "--name-only", "--diff-filter=D", "-z"],
                                        capture_output=True, check=False)
                require(result.returncode == 0, "git_inventory_failed")
                deleted = set(result.stdout.decode().split("\0"))
                selected = [n for n in selected if n not in deleted]
            scanner = Scanner(limits, tokens, load_fixtures(args.fixtures) if args.fixtures else None)
            result = scanner.scan(args.root, selected)
        elif args.operation == "preserve-credentials":
            require(args.destination is not None, "destination_required")
            result = preserve_credentials(args.root, args.destination)
        elif args.operation == "verify-private":
            require(args.destination is not None, "destination_required")
            result = verify_private(args.destination)
        else:
            require(args.destination is not None and args.allowlist is not None, "export_arguments_required")
            allowlist = safe.parse_json(read_file(args.allowlist.parent, args.allowlist.name, 1024**2))
            result = export_evidence(args.root, args.destination, allowlist, limits=limits, known_tokens=tokens)
        print(json.dumps(result, sort_keys=True))
        return 0 if result["status"] == "passed" else 1
    except (Error, OSError, ValueError, KeyError, TypeError, RecursionError):
        print(json.dumps({"status": "failed", "rule": "operation_refused"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

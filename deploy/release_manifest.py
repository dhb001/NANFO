"""Offline ADR021 release hashes and bounded, credential-free evidence bundles.

Build input selection belongs to manage.py's source_sha256 records. This tool
neither builds images nor runs acceptance. Export deliberately projects verifier
results to typed statuses: arbitrary diagnostic strings are never copied.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import secrets
import stat
import sys
import tarfile
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

LOCKS = ("backend/poetry.lock", "frontend/package-lock.json", "ai-engine/uv.lock")
MAX_FILE = 8 * 1024 * 1024
MAX_TOTAL = 64 * 1024 * 1024
MAX_ENTRIES = 4096
MAX_SOURCES = 20000
HEX = re.compile(r"[0-9a-f]{64}\Z")
PROJECT = re.compile(r"nanfo-deploy-verify-[0-9a-f]{32}\Z")
RESOURCE = re.compile(r"resources-[0-9a-f]{32}\.json\Z")
STATUSES = ("passed", "failed", "blocked", "pending")
FLAGS = (
    "core_passed",
    "all_green",
    "step15_complete",
    "live_authorized",
    "agents_idle_attested",
    "live_requested_lab",
    "live_requested_model",
)


class EvidenceError(Exception):
    """Constant diagnostics only; never echo input paths, JSON or subprocess output."""


def require(condition, message):
    if not condition:
        raise EvidenceError(message)


def canonical(value):
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def parse_json(data):
    def invalid_constant(_):
        raise EvidenceError("Nonfinite JSON value refused.")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "Duplicate JSON key.")
            result[key] = value
        return result

    try:
        return json.loads(
            data, object_pairs_hook=unique, parse_constant=invalid_constant
        )
    except (ValueError, UnicodeError, RecursionError):
        raise EvidenceError("Invalid JSON record.") from None


def safe_name(name):
    require(isinstance(name, str) and 0 < len(name) <= 240, "Invalid relative path.")
    parts = PurePosixPath(name).parts
    require(
        re.fullmatch(r"[A-Za-z0-9_./-]+", name)
        and str(PurePosixPath(name)) == name
        and not name.startswith("/")
        and all(part not in {".", ".."} for part in parts),
        "Unsafe relative path.",
    )
    require(
        not any(
            part.lower()
            in {
                "secrets",
                "keys",
                "backup",
                "restore",
                "binding",
                "models",
                "model-registry",
            }
            or part.startswith(".")
            or part.lower().endswith((".env", ".key", ".pem", ".p12", ".pfx"))
            for part in parts
        ),
        "Protected path refused.",
    )
    return name


@contextmanager
def directory_fd(path):
    """Open every ancestor without following links, including caller-supplied roots."""
    path = Path(path).absolute()
    require(".." not in path.parts, "Directory traversal refused.")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            child = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd
            )
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


def read_relative(root, name, *, limit=MAX_FILE):
    safe_name(name)
    parts = PurePosixPath(name).parts
    with directory_fd(root) as root_fd:
        fd = os.dup(root_fd)
        try:
            for part in parts[:-1]:
                child = os.open(
                    part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd
                )
                os.close(fd)
                fd = child
            source_fd = os.open(
                parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd
            )
            with os.fdopen(source_fd, "rb") as source:
                before = os.fstat(source.fileno())
                require(
                    stat.S_ISREG(before.st_mode) and before.st_nlink == 1,
                    "Regular single-link input required.",
                )
                require(before.st_size <= limit, "Input byte cap exceeded.")
                data = source.read(limit + 1)
                after = os.fstat(source.fileno())
                require(
                    len(data) == before.st_size <= limit
                    and (before.st_mtime_ns, before.st_ctime_ns)
                    == (after.st_mtime_ns, after.st_ctime_ns),
                    "Input changed while reading.",
                )
                return data
        finally:
            os.close(fd)


def read_path(path, *, limit=MAX_FILE):
    path = Path(path).absolute()
    return read_relative(path.parent, path.name, limit=limit)


def publish(path, data):
    """Durable, atomic, no-clobber publication inside an existing private directory."""
    path = Path(path).absolute()
    safe_name(path.name)
    with directory_fd(path.parent) as parent:
        info = os.fstat(parent)
        require(
            info.st_uid == os.geteuid() and not info.st_mode & 0o077,
            "Output parent must be owned and mode 0700.",
        )
        # Use descriptor-relative creation/publication, so parent renames cannot
        # redirect the output. Hardlink publication is atomic and never overwrites.
        name = ".release-" + secrets.token_hex(16)
        fd = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=parent,
        )
        try:
            with os.fdopen(fd, "wb") as target:
                target.write(data)
                target.flush()
                os.fsync(target.fileno())
            os.link(
                name,
                path.name,
                src_dir_fd=parent,
                dst_dir_fd=parent,
                follow_symlinks=False,
            )
        finally:
            os.unlink(name, dir_fd=parent)
            os.fsync(parent)


def descriptor(data):
    return {"bytes": len(data), "sha256": sha256(data)}


def validate_descriptor(value):
    require(
        isinstance(value, dict) and set(value) == {"bytes", "sha256"},
        "Invalid checksum descriptor.",
    )
    require(
        type(value["bytes"]) is int and 0 <= value["bytes"] <= MAX_FILE,
        "Invalid file size.",
    )
    require(
        isinstance(value["sha256"], str) and HEX.fullmatch(value["sha256"]),
        "Invalid SHA256.",
    )


def validate_manifest(value):
    require(
        isinstance(value, dict) and set(value) == {"schema", "files", "build_records"},
        "Invalid release manifest.",
    )
    require(value["schema"] == "nanfo-release-v1", "Unsupported release schema.")
    files, records = value["files"], value["build_records"]
    require(
        isinstance(files, dict) and 0 < len(files) <= MAX_SOURCES,
        "Invalid source inventory.",
    )
    require(
        isinstance(records, dict) and 0 < len(records) <= 64,
        "Invalid build record inventory.",
    )
    require(set(LOCKS).issubset(files), "All exact dependency locks are required.")
    for name, item in files.items():
        safe_name(name)
        validate_descriptor(item)
    for name, item in records.items():
        safe_name(name)
        require(
            isinstance(item, dict)
            and set(item) == {"record", "image_id", "source_paths"},
            "Invalid build record descriptor.",
        )
        validate_descriptor(item["record"])
        require(
            isinstance(item["image_id"], str)
            and re.fullmatch(r"sha256:[0-9a-f]{64}", item["image_id"]),
            "Exact image ID required.",
        )
        paths = item["source_paths"]
        require(
            isinstance(paths, list)
            and paths
            and all(isinstance(p, str) for p in paths),
            "Invalid build source list.",
        )
        require(
            paths == sorted(set(paths)) and set(paths).issubset(files),
            "Build source coverage invalid.",
        )
    require(
        set(LOCKS).issubset(
            {path for item in records.values() for path in item["source_paths"]}
        ),
        "Build records must cover every dependency lock.",
    )
    return value


def create_manifest(root, build_root, records, sources=()):
    require(
        0 < len(records) <= 64 and len(set(records)) == len(records),
        "Unique build records required.",
    )
    expected, builds = {}, {}
    for name in sorted(records):
        raw = read_relative(build_root, name)
        value = parse_json(raw)
        require(isinstance(value, dict), "Invalid build record.")
        hashes = value.get("source_sha256")
        require(
            isinstance(hashes, dict) and 0 < len(hashes) <= MAX_SOURCES,
            "Build source hashes required.",
        )
        for source, digest in hashes.items():
            safe_name(source)
            require(
                isinstance(digest, str) and HEX.fullmatch(digest),
                "Invalid build source hash.",
            )
            require(
                source not in expected or expected[source] == digest,
                "Conflicting build inputs.",
            )
            expected[source] = digest
        builds[name] = {
            "record": descriptor(raw),
            "image_id": value.get("image_id"),
            "source_paths": sorted(hashes),
        }
    require(
        set(LOCKS).issubset(expected), "Build records must cover every dependency lock."
    )
    names = set(expected) | set(LOCKS) | set(sources)
    require(len(names) <= MAX_SOURCES, "Source entry cap exceeded.")
    files = {}
    for name in sorted(names):
        raw = read_relative(root, name)
        files[name] = descriptor(raw)
        require(
            name not in expected or expected[name] == sha256(raw),
            "Source differs from recorded build input.",
        )
    return validate_manifest(
        {"schema": "nanfo-release-v1", "files": files, "build_records": builds}
    )


def verify_manifest(manifest, root, build_root):
    validate_manifest(manifest)
    recreated = create_manifest(
        root, build_root, list(manifest["build_records"]), list(manifest["files"])
    )
    require(recreated == manifest, "Release checksums or build coverage changed.")


def project_result(raw):
    """No raw detail/failure/path strings, tokens, or unknown fields cross this boundary."""
    value = parse_json(raw)
    require(
        isinstance(value, dict) and isinstance(value.get("cases"), dict),
        "Verifier cases required.",
    )
    cases = value["cases"]
    require(0 < len(cases) <= 128, "Verifier case cap exceeded.")
    # Case names are code-owned, not arbitrary text from an input JSON document.
    try:
        from deploy.verify import CASES
        from deploy.schema_contract import HISTORICAL_MIGRATION_CASES
    except ModuleNotFoundError:
        from verify import CASES
        from schema_contract import HISTORICAL_MIGRATION_CASES
    # Archived ADR020 matrices remain exportable after the live schema advances.
    require(
        set(cases).issubset({*CASES, *HISTORICAL_MIGRATION_CASES}),
        "Unknown verifier case.",
    )
    statuses = {}
    for name, row in cases.items():
        require(
            isinstance(row, dict) and row.get("status") in STATUSES,
            "Invalid verifier status.",
        )
        statuses[name] = {"status": row["status"]}
    flags = {}
    for name in FLAGS:
        if name in value:
            require(type(value[name]) is bool, "Invalid verifier flag.")
            flags[name] = value[name]
    return canonical(
        {
            "schema": "nanfo-verifier-status-v1",
            "cases": statuses,
            "counts": {
                status: sum(row["status"] == status for row in statuses.values())
                for status in STATUSES
            },
            "reported_flags": flags,
        }
    )


def project_resources(raw):
    value = parse_json(raw)
    require(
        isinstance(value, dict) and set(value) == {"containers", "volumes", "networks"},
        "Invalid resource ledger.",
    )
    for kind, entries in value.items():
        require(
            isinstance(entries, dict) and len(entries) <= MAX_ENTRIES,
            "Resource count cap exceeded.",
        )
        for identity, project in entries.items():
            require(
                isinstance(project, str) and PROJECT.fullmatch(project),
                "Invalid resource project.",
            )
            if kind == "volumes":
                valid = re.fullmatch(
                    re.escape(project) + r"_[a-z][a-z0-9_]{0,63}", identity
                )
            elif kind == "networks":
                # Existing verifier records Docker network ls's short IDs.
                valid = re.fullmatch(r"(?:[0-9a-f]{12}|[0-9a-f]{64})", identity)
            else:
                valid = HEX.fullmatch(identity)
            require(valid, "Invalid resource identity.")
    return canonical(value)


def evidence_name(name):
    return name == "evidence/result.json" or (
        name.startswith("evidence/")
        and RESOURCE.fullmatch(name.removeprefix("evidence/"))
    )


def export_bundle(manifest_path, run_dir, output):
    run_dir, output = Path(run_dir).absolute(), Path(output).absolute()
    require(
        not output.is_relative_to(run_dir),
        "Durable output must be outside the temporary run.",
    )
    raw = read_path(manifest_path)
    manifest = validate_manifest(parse_json(raw))
    payloads = {"release.json": canonical(manifest)}
    originals = {}
    # Exact filename allowlist; no recursive walk or generic include option.
    with directory_fd(run_dir / "evidence") as fd:
        names = []
        with os.scandir(fd) as entries:
            for index, entry in enumerate(entries):
                require(index < MAX_ENTRIES - 2, "Evidence entry cap exceeded.")
                if entry.name == "result.json" or RESOURCE.fullmatch(entry.name):
                    names.append(entry.name)
        require("result.json" in names, "Completed verifier result required.")
    total = len(payloads["release.json"])
    for name in sorted(names):
        path = "evidence/" + name
        raw = read_relative(run_dir, path)
        total += len(raw)
        require(total <= MAX_TOTAL, "Evidence byte cap exceeded.")
        originals[path] = descriptor(raw)
        payloads[path] = (
            project_result(raw) if name == "result.json" else project_resources(raw)
        )
    catalog = {
        "schema": "nanfo-evidence-v1",
        "files": {name: descriptor(data) for name, data in sorted(payloads.items())},
        "original_evidence": originals,
    }
    payloads["checksums.json"] = canonical(catalog)
    data = pack(payloads)
    require(len(data) <= MAX_TOTAL, "Archive byte cap exceeded.")
    verify_bundle_bytes(data)
    publish(output, data)
    return sha256(data)


def pack(payloads):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for name, data in sorted(payloads.items()):
            member = tarfile.TarInfo(name)
            member.size, member.mode = len(data), 0o600
            archive.addfile(member, io.BytesIO(data))
    return buffer.getvalue()


def verify_bundle_bytes(data, expected_sha256=None):
    require(len(data) <= MAX_TOTAL, "Archive byte cap exceeded.")
    if expected_sha256 is not None:
        require(
            HEX.fullmatch(expected_sha256) and sha256(data) == expected_sha256,
            "Archive checksum mismatch.",
        )
    payloads = {}
    total = 0
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
            for member in archive:
                safe_name(member.name)
                require(
                    member.name in {"release.json", "checksums.json"}
                    or evidence_name(member.name),
                    "Archive member not allowlisted.",
                )
                require(
                    member.name not in payloads and len(payloads) < MAX_ENTRIES,
                    "Duplicate member or entry cap exceeded.",
                )
                require(
                    member.type == tarfile.REGTYPE
                    and not member.pax_headers
                    and not member.linkname
                    and not member.sparse,
                    "Only plain regular archive files accepted.",
                )
                require(
                    member.mode == 0o600
                    and member.uid == member.gid == member.mtime == 0
                    and not member.uname
                    and not member.gname,
                    "Noncanonical archive metadata.",
                )
                require(
                    0 <= member.size <= MAX_FILE, "Archive member byte cap exceeded."
                )
                total += member.size
                require(total <= MAX_TOTAL, "Expanded byte cap exceeded.")
                payloads[member.name] = archive.extractfile(member).read(MAX_FILE + 1)
                require(
                    len(payloads[member.name]) == member.size,
                    "Truncated archive member.",
                )
    except (tarfile.TarError, ValueError):
        raise EvidenceError("Invalid uncompressed evidence archive.") from None
    require(
        {"release.json", "checksums.json", "evidence/result.json"}.issubset(payloads),
        "Required archive members missing.",
    )
    require(pack(payloads) == data, "Noncanonical archive or trailing bytes.")
    catalog = parse_json(payloads.pop("checksums.json"))
    require(
        isinstance(catalog, dict)
        and set(catalog) == {"schema", "files", "original_evidence"}
        and catalog["schema"] == "nanfo-evidence-v1",
        "Invalid checksum catalog.",
    )
    require(
        catalog["files"] == {name: descriptor(raw) for name, raw in payloads.items()},
        "Archive content checksum mismatch.",
    )
    originals = catalog["original_evidence"]
    require(
        isinstance(originals, dict)
        and set(originals) == set(payloads) - {"release.json"},
        "Invalid original evidence inventory.",
    )
    for item in originals.values():
        validate_descriptor(item)
    validate_manifest(parse_json(payloads["release.json"]))
    for name, raw in payloads.items():
        if name == "evidence/result.json":
            value = parse_json(raw)
            require(
                isinstance(value, dict)
                and set(value) == {"schema", "cases", "counts", "reported_flags"},
                "Invalid projected result.",
            )
            flags = value["reported_flags"]
            require(
                isinstance(flags, dict) and set(flags).issubset(FLAGS),
                "Invalid projected flags.",
            )
            require(
                project_result(canonical({"cases": value["cases"], **flags})) == raw,
                "Noncanonical or unsafe result projection.",
            )
        elif evidence_name(name):
            require(project_resources(raw) == raw, "Noncanonical resource ledger.")
    return {
        "archive_sha256": sha256(data),
        "files": len(payloads),
        "integrity_verified": True,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser(
        "create", help="Hash exact locks and source_sha256 build records"
    )
    verify = commands.add_parser(
        "verify", help="Recheck manifest against current source and build records"
    )
    for command in (create, verify):
        command.add_argument("--root", type=Path, required=True)
        command.add_argument("--build-root", type=Path, required=True)
    create.add_argument("--build-record", action="append", required=True)
    create.add_argument("--source", action="append", default=[])
    create.add_argument("--output", type=Path, required=True)
    verify.add_argument("--manifest", type=Path, required=True)
    export = commands.add_parser(
        "export", help="Export only projected result and typed resource ledgers"
    )
    export.add_argument("--manifest", type=Path, required=True)
    export.add_argument("--run-dir", type=Path, required=True)
    export.add_argument("--output", type=Path, required=True)
    archive = commands.add_parser(
        "verify-archive", help="Check archive without extracting or Docker"
    )
    archive.add_argument("--archive", type=Path, required=True)
    archive.add_argument(
        "--sha256", required=True, help="Trusted SHA256 printed by export"
    )
    args = parser.parse_args(argv)
    try:
        if args.command == "create":
            value = create_manifest(
                args.root, args.build_root, args.build_record, args.source
            )
            raw = canonical(value)
            require(len(raw) <= MAX_FILE, "Manifest byte cap exceeded.")
            publish(args.output, raw)
            result = {"manifest_sha256": sha256(raw)}
        elif args.command == "verify":
            raw = read_path(args.manifest)
            verify_manifest(parse_json(raw), args.root, args.build_root)
            result = {"manifest_sha256": sha256(raw), "inputs_verified": True}
        elif args.command == "export":
            result = {
                "archive_sha256": export_bundle(
                    args.manifest, args.run_dir, args.output
                )
            }
        else:
            result = verify_bundle_bytes(
                read_path(args.archive, limit=MAX_TOTAL), args.sha256
            )
    except (EvidenceError, OSError, ValueError, TypeError, RecursionError):
        print(
            "Release evidence refused: invalid, changed, unsafe, oversized or unavailable input/output.",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

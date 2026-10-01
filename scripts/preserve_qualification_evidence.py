"""Offline ADR024 allowlisted preservation. Never launches a lab or installs a model.

inspect performs the same selection, secret screening and pin checks as preserve.
preserve creates new protected roots only; verify needs no historical /tmp inputs.
Historical bytes are copied verbatim. New receipts describe relocation separately.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import stat
import sys
import zipfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy"))
import release_manifest as safe

ARTIFACTS = ROOT / "ai-engine/artifacts/adr024-qualified-001"
DOCUMENTS = ROOT / "docs/project/CompletionProgram/QualificationEvidence-ADR024"
# Historical acquisition roots (defaults; wiped scratch on most hosts). Override each with
# --source-root GROUP=PATH; the roots actually used are recorded as historical_roots.
SOURCES = {
    "evaluation": Path("/tmp/opencode/nanfo-adr024-evaluation-002"),
    "live": Path("/tmp/opencode/nanfo-live-acceptance-7ngrbdgv"),
    "native": Path("/tmp/opencode/native-driver-02z3yisx"),
    "recovery": Path("/tmp/opencode/nanfo-adr024-runtime-xfwykjez"),
    "review": Path("/tmp/opencode"),
    "repository": ROOT,
}
PARENT = "5b8818af655ec8efce5d3bc3def27db599f3e0df379a0ae263dcefb5f72a80a5"
DERIVED = "77dae44acab722a5a6a2e87d952a6cca65e1c4eea102a089830a8401b521d614"
WEIGHTS = "3e7e38ab4297ffd4b32b9c32d64af4b45e5f5ed1b2a74f9926f23379b0b0f967"
POLICIES = ("ppo", "heuristic", "constant1", "ospf", "constant0")
MAX_TOTAL = 256 * 1024**2
MAX_FILE = 16 * 1024**2
MAX_DOCS = 2 * 1024**2
MAX_ENTRIES = 4096
EVALUATION = (
    "checkpoint.ptz", "parent-checkpoint.ptz", "plan.json", "selection.json",
    "lineage.json", "seed-audit.json", "test-report.json", "qualification.json",
    "outcome.json", "independent-verification.json", "deployment-registry.json",
    "live-registry.template.json", "recorded-history-path0.json",
    "recorded-history-path1.json", "campaign-runner.py", "recovery-runner.py",
    "started.json",
)
LIVE = (
    "plan.json", "result.json", "cleanup.json", "qualification.json", "registry.json",
    "source-manifest.json", "seed-audit.json", "durable-decisions.json", "evidence-audit.json",
)
NATIVE = (
    "protocol.json", "result.json", "reconstruction.json", "sources.json", "cleanup.json",
    "continuous-release-result.json", "continuous-release-cleanup.json", "identity.jsonl",
)
REVIEWS = (
    "adr024-final-live-independent.json", "adr024-final-native-independent.json",
    "adr024-final-native-readback.json", "adr024-final-native-owner-audit-replay.json",
    "adr024-independent-runtime-review-final-002.json",
    "adr024_final_live_review.py", "adr024_final_native_review.py",
    "adr024_final_native_readback.py", "adr024_independent_runtime_review.py",
)
COMPACT = {
    *(f"evaluation/{name}" for name in (
        "plan.json", "selection.json", "lineage.json", "outcome.json", "qualification.json",
        "independent-verification.json", "deployment-registry.json", "live-registry.template.json")),
    *(f"live/{name}" for name in ("plan.json", "result.json", "cleanup.json", "source-manifest.json")),
    *(f"native/{name}" for name in ("protocol.json", "result.json", "reconstruction.json", "sources.json", "cleanup.json")),
    *(f"review/{name}" for name in REVIEWS if name.endswith(".json")),
    "recovery/recovery.json",
}
UUID = r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}"
SECRET_KEY = re.compile(
    r"(?:password|passwd|secret|secret_key|signing_key|private_key|api_key|access_token|"
    r"refresh_token|admission_token|token|credentials|credential|cookie|set-cookie|env|environment)", re.IGNORECASE
)
SECRET_TEXT = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|\bBearer\s+[A-Za-z0-9._~+/-]{8,}|"
    r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}|"
    r"[a-z][a-z0-9+.-]*://[^\s/:{}]+:[^\s/@{}]+@|"
    r"(?i:(?:password|passwd|secret_key|signing_key|api_key|access_token|admission_token)"
    r"\s*[=:]\s*[\"'][A-Za-z0-9/+_.-]{12,}[\"'])|"
    r"(?i:(?:password|passwd|secret_key|signing_key|api_key|access_token|admission_token)"
    r"=[A-Za-z0-9/+_.-]{8,}(?=[\s\"']|$))"
)


def require(ok, message):
    safe.require(ok, message)


def canonical(value):
    return safe.canonical(value)


def scan_value(value):
    if isinstance(value, dict):
        for key, child in value.items():
            require(not SECRET_KEY.fullmatch(key) or child in (None, False, "", [], {})
                    or (key == "environment" and child == "isolated-emulation"),
                    "Credential/environment field refused.")
            scan_value(child)
    elif isinstance(value, list):
        for child in value:
            scan_value(child)
    elif isinstance(value, str):
        require(not SECRET_TEXT.search(value), "Credential-like content refused.")
        # Native command results sometimes embed a complete JSON document in stdout.
        if value.lstrip().startswith(("{", "[")):
            try:
                embedded = safe.parse_json(value.encode())
            except safe.EvidenceError:
                return
            scan_value(embedded)


def screen(name, data):
    """Fail closed; never redact an original and never print matched secret content."""
    if name.endswith(".ptz"):
        require(safe.sha256(data) in (PARENT, DERIVED), "Unpinned binary model refused.")
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            require(set(archive.namelist()) == {"manifest.json", "weights.pt"}
                    and len(archive.infolist()) == 2, "Unexpected model member.")
            require(all(item.file_size <= MAX_FILE for item in archive.infolist()), "Model size cap.")
            scan_value(safe.parse_json(archive.read("manifest.json")))
            require(safe.sha256(archive.read("weights.pt")) == WEIGHTS, "Tensor bytes changed.")
        return
    text = data.decode("utf-8")
    require(not SECRET_TEXT.search(text), "Credential-like content refused.")
    if name.endswith(".json"):
        scan_value(safe.parse_json(data))
    elif name.endswith(".jsonl"):
        for line in data.splitlines():
            scan_value(safe.parse_json(line))


def names(root, relative=""):
    """Bounded, descriptor-relative traversal; no symlinks, FIFOs or devices."""
    result = []

    def walk(fd, prefix):
        with os.scandir(fd) as entries:
            for entry in sorted(entries, key=lambda item: item.name):
                name = prefix + entry.name
                info = entry.stat(follow_symlinks=False)
                require(not stat.S_ISLNK(info.st_mode), "Source tree link refused.")
                if stat.S_ISDIR(info.st_mode):
                    child = os.open(entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                    try:
                        walk(child, name + "/")
                    finally:
                        os.close(child)
                else:
                    require(stat.S_ISREG(info.st_mode), "Special source file refused.")
                    result.append((name, info.st_size))
                    require(len(result) <= MAX_ENTRIES, "Entry cap exceeded.")

    if relative:
        safe.safe_name(relative)
    with safe.directory_fd(root / relative) as fd:
        walk(fd, relative + "/" if relative else "")
    return result


def dynamic_allowed(group, name):
    lab = rf"experiment-(?:ospf-readiness|{UUID}-(?:schedule|\d{{2}}))\.json"
    if group == "evaluation":
        return bool(re.fullmatch(r"(?:ppo|heuristic|constant[01]|ospf)-lab-output/" + lab, name))
    if group == "live":
        return bool(re.fullmatch(
            rf"observations/(?:snapshot\.json(?:\.attached\.json)?|receipt-{UUID}\.json)|"
            r"path[01]-(?:monitor|recommend-[12]|stale-blocked)-decision\.json|"
            r"path[01]/(?:lab-identity|attached|snapshot-[012]|fresh-helper|stale|disconnected)\.json|"
            r"path[01]/feed/(?:evidence\.jsonl|(?:header-ready|frame-[012]|closed)\.json)|"
            r"path[01]/lab-output/" + lab, name))
    if group == "native":
        case = r"(?:STOP-(?:[0-9]|1[012])|expired-0|binding-refusal-0|foreign-12|restart-3|lost-receipt-3|recovery-interrupted-3|normal-12)"
        leaf = (r"(?:prepared\.json|prepared\.sha256|(?:apply|recover)-[0-9a-f]{32}\.jsonl|"
                r"(?:apply|recover)-result-[0-9a-f]{32}\.json|"
                r"(?:apply-process|recovery-process-[01]|case-complete|foreign-refusal|"
                r"recovery-interruption|unsealed-verification)\.json)")
        return bool(re.fullmatch(r"action[01]/(?:fixture\.jsonl|namespaces\.json|" + case + "/" + leaf + ")", name))
    return False


def selected():
    """Exact static names plus narrowly typed campaign paths, never a generic copy tree."""
    items = {}
    inventory = {}

    def add(group, name, destination=None, pin=None):
        safe.safe_name(name)
        destination = destination or ("model/" + name if group == "evaluation" else group + "/" + name)
        safe.safe_name(destination)
        require(destination not in items, "Duplicate destination.")
        data = safe.read_relative(SOURCES[group], name, limit=MAX_FILE)
        if pin is not None:
            require(safe.sha256(data) == pin, "Source pin mismatch.")
        try:
            screen(name, data)
        except (safe.EvidenceError, UnicodeError):
            # Only allowlisted relative names are printed; never document contents.
            raise safe.EvidenceError("Secret/content screening failed for " + group + "/" + name) from None
        items[destination] = (group, name, data)

    for group, fixed in (("evaluation", EVALUATION), ("live", LIVE), ("native", NATIVE)):
        inventory[group] = names(SOURCES[group])
        for name in fixed:
            add(group, name)
        for name, _ in inventory[group]:
            if dynamic_allowed(group, name):
                add(group, name)
    registry = safe.parse_json(items["model/live-registry.template.json"][2])
    for name, pin in registry["source_sha256"].items():
        require(re.fullmatch(r"[a-z_]+\.py", name), "Unexpected model source name.")
        add("evaluation", "source/" + name, pin=pin)
    for policy in POLICIES:
        for name in ("summary.json", "evidence.jsonl", "feed-attachment.json"):
            add("evaluation", f"test-{policy}/{name}")
        add("evaluation", policy + "-cleanup.json")
    live_pins = safe.parse_json(items["live/source-manifest.json"][2])
    for name, pin in live_pins.items():
        require(re.fullmatch(r"(?:backend/app/modules/autonomy|backend/scripts|scripts|emulation)/[a-z_]+\.py", name),
                "Unexpected live source name.")
        add("repository", name, "live/source/" + name, pin)
    native_pins = safe.parse_json(items["native/sources.json"][2])
    for name, pin in native_pins.items():
        # No build caches, dotfiles, compose/environment files or arbitrary binaries.
        if re.fullmatch(r"Dockerfile|backend/scripts/verify_native_driver\.py|emulation/(?:[a-z_]+\.py|tests/test_[a-z_]+\.py|requirements\.txt|apt-sources\.list|Dockerfile|[A-Z0-9-]+\.md|logging\.conf|ruff\.toml)", name):
            add("native", "source/" + name, pin=pin)
    for name in REVIEWS:
        add("review", name)
    for name in ("scripts/preserve_qualification_evidence.py", "deploy/release_manifest.py",
                 "scripts/verify_adr024_campaign.py"):
        add("repository", name, "preservation-source/" + name)
    for name in ("recovery.json", "audit.json", "Dockerfile.recovery", "base-dependencies.json"):
        add("recovery", name)
    recovery = safe.parse_json(items["recovery/recovery.json"][2])
    for name, pin in recovery["archive_all_files"].items():
        # The recovery map is authenticated by the archived source hash in recovery.json.
        if not any(part.startswith(".") for part in Path(name).parts):
            add("recovery", name, pin=pin)
    for name, pin in recovery["dependency_locks"].items():
        add("repository", "ai-engine/artifacts/adr014-001/source/" + name,
            "model/dependencies/" + name, pin)
    require(sum(len(row[2]) for row in items.values()) <= MAX_TOTAL, "Total byte cap exceeded.")
    require(len(items) <= MAX_ENTRIES, "Entry cap exceeded.")
    return items, inventory


def check_references(registry, read):
    count = 0

    def walk(value):
        nonlocal count
        if isinstance(value, dict):
            if set(value) == {"path", "sha256", "size_bytes"}:
                safe.safe_name(value["path"])
                data = read(value["path"])
                require(len(data) == value["size_bytes"] and safe.sha256(data) == value["sha256"],
                        "Relocated registry reference mismatch.")
                count += 1
            else:
                for child in value.values():
                    walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(registry)
    safe.safe_name(registry["source_directory"])
    for name, pin in registry["source_sha256"].items():
        safe.safe_name(name)
        require(safe.sha256(read(registry["source_directory"] + "/" + name)) == pin,
                "Relocated frozen source mismatch.")
    return count


def validate_model(read):
    parent, derived = read("parent-checkpoint.ptz"), read("checkpoint.ptz")
    require(safe.sha256(parent) == PARENT and safe.sha256(derived) == DERIVED, "Immutable model pin mismatch.")
    screen("parent-checkpoint.ptz", parent)
    screen("checkpoint.ptz", derived)
    with zipfile.ZipFile(io.BytesIO(parent)) as a, zipfile.ZipFile(io.BytesIO(derived)) as b:
        require(a.read("weights.pt") == b.read("weights.pt"), "Tensor payload differs.")
        before, after = safe.parse_json(a.read("manifest.json")), safe.parse_json(b.read("manifest.json"))
    before["lab_provenance"]["lab_image_id"] = after["lab_provenance"]["lab_image_id"]
    require(before == after, "Non-image model manifest change.")
    return {name: check_references(safe.parse_json(read(name)), read)
            for name in ("deployment-registry.json", "live-registry.template.json")}


def make_directory(path, *, exclusive=False):
    """Create via a pinned parent descriptor; reject existing links and loose permissions."""
    with safe.directory_fd(path.parent) as parent:
        info = os.fstat(parent)
        require(info.st_uid == os.geteuid() and not info.st_mode & 0o022, "Unprotected output ancestor.")
        try:
            os.mkdir(path.name, 0o700, dir_fd=parent)
            os.fsync(parent)
        except FileExistsError:
            if exclusive:
                raise safe.EvidenceError("Output exists; refusing overwrite.") from None
        fd = os.open(path.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        try:
            info = os.fstat(fd)
            require(info.st_uid == os.geteuid() and info.st_mode & 0o777 == 0o700, "Output must be owned mode 0700.")
        finally:
            os.close(fd)


def publish(root, name, data):
    safe.safe_name(name)
    parent = root
    for part in Path(name).parts[:-1]:
        parent /= part
        make_directory(parent)
    safe.publish(root / name, data)
    require(safe.read_relative(root, name, limit=MAX_FILE) == data, "Copy readback mismatch.")


def output_roots(artifacts, documents):
    artifacts, documents = artifacts.absolute(), documents.absolute()
    for path in (artifacts, documents):
        require(".." not in path.parts and not path.is_relative_to(Path("/tmp")), "Durable output required.")
        require(not path.exists() and not path.is_symlink(), "Output exists; refusing overwrite.")
        with safe.directory_fd(path.parent):
            pass
        # Existing operator-owned ancestors may be 0755, but never group/world writable.
        for ancestor in path.parents:
            info = ancestor.lstat()
            require(info.st_uid in (0, os.geteuid()) and not info.st_mode & 0o022,
                    "Unprotected output ancestor.")
        for source in SOURCES.values():
            if source != ROOT:
                require(not path.is_relative_to(source) and not source.is_relative_to(path), "Source/output overlap.")
    require(not artifacts.is_relative_to(documents) and not documents.is_relative_to(artifacts), "Output roots overlap.")
    return artifacts, documents


def preservation(artifacts, documents, *, inspect=False):
    items, inventory = selected()
    read_model = lambda name: items["model/" + name][2]
    refs = validate_model(read_model)
    refs["historical-live-registry"] = check_references(safe.parse_json(items["live/registry.json"][2]), read_model)
    counts = Counter()
    sizes = Counter()
    for group, _, data in items.values():
        counts[group] += 1
        sizes[group] += len(data)
    excluded = {}
    for group, entries in inventory.items():
        retained = {name for origin, name, _ in items.values() if origin == group}
        omitted = [(name, size) for name, size in entries if name not in retained]
        excluded[group] = {"files": len(omitted), "bytes": sum(size for _, size in omitted)}
    summary = {"selected_files": len(items), "selected_bytes": sum(sizes.values()),
               "groups": {key: {"files": counts[key], "bytes": sizes[key]} for key in sorted(counts)},
               "excluded": excluded, "registry_references": refs}
    if inspect:
        return summary
    artifacts, documents = output_roots(artifacts, documents)
    make_directory(artifacts, exclusive=True)
    make_directory(documents, exclusive=True)
    rows, docs = [], {}
    for destination, (group, name, data) in sorted(items.items()):
        publish(artifacts, destination, data)
        logical = group + "/" + name
        doc_path = logical if logical in COMPACT else None
        if doc_path:
            publish(documents, doc_path, data)
            docs[doc_path] = safe.descriptor(data)
        rows.append({"source_root": group, "source_path": name, "artifact_path": destination,
                     "document_path": doc_path, "source_sha256": safe.sha256(data),
                     "destination_sha256": safe.sha256(data), "bytes": len(data)})
    # Root references, including snapshot paths, are relative to this new map.
    relocation = {
        "schema": "nanfo-adr024-relocation-v1",
        "historical_roots": {key: str(value) for key, value in SOURCES.items()},
        "relocated_roots": {"evaluation": "model", "live": "live", "native": "native", "recovery": "recovery", "review": "review"},
        "registry": {"model_root": "model", "template": "model/live-registry.template.json",
                     "historical_installation": "live/registry.json", "observation_root": "live/observations"},
        "historical_bytes_rewritten": False,
        "historical_installation_is_current_authority": False,
        "excluded_categories": ["admission files/tokens", "environments and container inspections",
                                "signing keys/credentials", "generic process/build logs", "locks/release signals",
                                "native manual authority files", "build caches/dotfiles/compose configuration"],
        "verification_limits": ["Historical absolute paths and inode metadata remain historical.",
                                "Excluded admission and container environment bytes cannot be re-audited from this export.",
                                "No Docker image layers, runtime packages, private stores or physical RF evidence exported."],
        "summary": summary,
        "files": rows,
    }
    raw_manifest = {"schema": "nanfo-adr024-raw-manifest-v1", "files": {
        name: safe.descriptor(data) for name, (_, _, data) in sorted(items.items())}}
    source_hashes = {"schema": "nanfo-adr024-source-hashes-v1", "files": {
        name: safe.descriptor(data) for name, (_, _, data) in sorted(items.items())
        if "/source/" in name or name.startswith("recovery/emulation/") or name.endswith(".py")}}
    for name, value in (("relocation-receipt.json", relocation), ("raw-manifest.json", raw_manifest),
                        ("source-hashes.json", source_hashes)):
        data = canonical(value)
        publish(documents, name, data)
        publish(artifacts, name, data)
        docs[name] = safe.descriptor(data)
    require(sum(item["bytes"] for item in docs.values()) <= MAX_DOCS, "Compact document byte cap exceeded.")
    checksums = canonical({"schema": "nanfo-adr024-document-checksums-v1", "files": docs})
    publish(documents, "checksums.json", checksums)
    publish(artifacts, "document-checksums.json", checksums)
    # Last marker only after every exact-byte copy and receipt has been fsynced/read back.
    result = verify(artifacts, documents)
    result["checksums_sha256"] = safe.sha256(checksums)
    publish(documents, "preservation-complete.json", canonical(result))
    publish(artifacts, "preservation-complete.json", canonical(result))
    return result


def verify(artifacts, documents):
    """Read-only integrity, credentials, tensor identity and relative registry closure."""
    checksums = safe.parse_json(safe.read_relative(documents, "checksums.json"))
    require(checksums["schema"] == "nanfo-adr024-document-checksums-v1", "Checksum schema mismatch.")
    for name, descriptor in checksums["files"].items():
        require(safe.descriptor(safe.read_relative(documents, name)) == descriptor, "Document checksum mismatch.")
    receipt = safe.parse_json(safe.read_relative(documents, "relocation-receipt.json"))
    require(receipt["schema"] == "nanfo-adr024-relocation-v1", "Receipt schema mismatch.")
    require(len(receipt["files"]) <= MAX_ENTRIES, "Entry cap exceeded.")
    expected = {}
    total = 0
    for item in receipt["files"]:
        name = item["artifact_path"]
        require(name not in expected, "Duplicate artifact path.")
        data = safe.read_relative(artifacts, name, limit=MAX_FILE)
        require(item["source_sha256"] == item["destination_sha256"] == safe.sha256(data)
                and item["bytes"] == len(data), "Relocation byte mismatch.")
        screen(name, data)
        expected[name] = safe.descriptor(data)
        total += len(data)
        require(total <= MAX_TOTAL, "Total byte cap exceeded.")
        if item["document_path"]:
            require(safe.read_relative(documents, item["document_path"]) == data, "Compact copy mismatch.")
    raw = safe.parse_json(safe.read_relative(documents, "raw-manifest.json"))
    require(raw["files"] == expected, "Raw manifest mismatch.")
    for name in ("relocation-receipt.json", "raw-manifest.json", "source-hashes.json"):
        require(safe.read_relative(artifacts, name) == safe.read_relative(documents, name), "Receipt copy mismatch.")
    require(safe.read_relative(artifacts, "document-checksums.json") == safe.read_relative(documents, "checksums.json"),
            "Checksum copy mismatch.")
    artifact_names = {name for name, _ in names(artifacts)}
    require(artifact_names - {"preservation-complete.json"} == set(expected) | {
        "raw-manifest.json", "source-hashes.json", "relocation-receipt.json", "document-checksums.json"},
        "Unexpected or missing artifact files.")
    require({name for name, _ in names(documents)} - {"preservation-complete.json"}
            == set(checksums["files"]) | {"checksums.json"}, "Unexpected document files.")
    for root in (artifacts, documents):
        for name, _ in names(root):
            info = (root / name).lstat()
            require(info.st_uid == os.geteuid() and info.st_mode & 0o777 == 0o600,
                    "Evidence file must be owned mode 0600.")
    read_model = lambda name: safe.read_relative(artifacts / "model", name, limit=MAX_FILE)
    references = validate_model(read_model)
    live = safe.parse_json(safe.read_relative(artifacts, "live/registry.json"))
    references["historical-live-registry"] = check_references(live, read_model)
    for scope in live["scopes"]:
        safe.read_relative(artifacts / "live/observations", scope["snapshot_path"])
    return {"schema": "nanfo-adr024-preservation-v1", "status": "passed", "files": len(expected),
            "artifact_payload_bytes": total,
            "document_payload_bytes": sum(row["bytes"] for row in checksums["files"].values()),
            "registry_references": references, "original_checkpoint_sha256": PARENT,
            "derived_checkpoint_sha256": DERIVED, "tensor_payload_sha256": WEIGHTS,
            "credentials_screened": True, "historical_bytes_rewritten": False, "lab_started": False}


def replay(artifacts, documents):
    """Use the original frozen loader/report implementation, offline and inference-only."""
    import contextlib
    import importlib
    import importlib.util

    result = verify(artifacts, documents)
    root = artifacts / "model"
    source = root / "source"
    spec = importlib.util.spec_from_file_location(
        "_adr024_preserved", source / "__init__.py", submodule_search_locations=[str(source)])
    package = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = package
    spec.loader.exec_module(package)
    cli = importlib.import_module(spec.name + ".cli")
    plan = safe.parse_json(safe.read_relative(root, "plan.json"))
    report = cli.report([root / f"test-{policy}/summary.json" for policy in plan["policy_order"]],
                        checkpoint=root / "checkpoint.ptz")
    require(report == safe.parse_json(safe.read_relative(root, "test-report.json")),
            "Frozen report reconstruction differs.")
    inferences = {}
    for scenario in ("path0", "path1"):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = cli.main(["infer", "--checkpoint", str(root / "checkpoint.ptz"),
                             "--history", str(root / f"recorded-history-{scenario}.json")])
        require(code == 0, "Frozen offline inference failed.")
        inferred = safe.parse_json(stdout.getvalue().encode())
        require(inferred["action"] == (1 if scenario == "path0" else 0), "Recorded direction mismatch.")
        inferences[scenario] = inferred
    result.update(frozen_report_exact=True, frozen_recorded_inference=inferences,
                  current_live_authorization=False)
    return result


def finalize(artifacts, documents):
    """Complete an interrupted post-copy verification; never recopy or overwrite bytes."""
    result = verify(artifacts, documents)
    result["checksums_sha256"] = safe.sha256(safe.read_relative(documents, "checksums.json"))
    data = canonical(result)
    for root in (documents, artifacts):
        try:
            existing = safe.read_relative(root, "preservation-complete.json")
        except FileNotFoundError:
            publish(root, "preservation-complete.json", data)
        else:
            require(existing == data, "Existing completion marker differs.")
    return result


def source_roots(values):
    """GROUP=PATH overrides for acquisition roots; the repository root is never replaced."""
    roots = dict(SOURCES)
    for value in values or ():
        group, separator, path = value.partition("=")
        require(separator == "=" and group in SOURCES and group != "repository", "Unknown source root group.")
        require(Path(path).is_absolute() and ".." not in Path(path).parts, "Source root must be absolute.")
        roots[group] = Path(path)
    return roots


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("inspect", "preserve", "verify", "replay", "finalize"))
    parser.add_argument("--artifacts", type=Path, default=ARTIFACTS)
    parser.add_argument("--documents", type=Path, default=DOCUMENTS)
    parser.add_argument("--source-root", action="append", metavar="GROUP=PATH",
                        help="acquisition root for evaluation|live|native|recovery|review")
    args = parser.parse_args()
    os.umask(0o077)
    sys.dont_write_bytecode = True
    try:
        SOURCES.update(source_roots(args.source_root))
        result = (finalize(args.artifacts, args.documents) if args.operation == "finalize" else
                  replay(args.artifacts, args.documents) if args.operation == "replay" else
                  verify(args.artifacts, args.documents) if args.operation == "verify" else
                  preservation(args.artifacts, args.documents, inspect=args.operation == "inspect"))
        print(json.dumps(result, indent=2, sort_keys=True))
    except (safe.EvidenceError, OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as exc:
        message = str(exc) if isinstance(exc, safe.EvidenceError) else type(exc).__name__
        print("Preservation refused: " + message, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

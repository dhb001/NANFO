#!/usr/bin/env python3
"""Recover ADR014 bytes and prepare a distinct, non-qualifying ADR024 evaluation image.

No lab launch, measurements, training, tag replacement, or historical writes.
Docker probes run only static inspection/tests, unprivileged and without networking.
"""

import argparse
import contextlib
import hashlib
import importlib
import importlib.util
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tarfile
import tempfile
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[1]
AI = ROOT / "ai-engine"
TRAIN = AI / "artifacts/adr014-001"
HOLDOUT = AI / "artifacts/adr014-holdout-001"
ARCHIVE = ROOT / "emulation/output/adr015-prechange-v4-source.tar.gz"
ARCHIVE_HASH = "444663dc3a7223044a9e8830ba5dd24cd3e1b041c60dc278e4bba56eb7252384"
CHECKPOINT = TRAIN / "train-06/checkpoint.ptz"
CHECKPOINT_HASH = "5b8818af655ec8efce5d3bc3def27db599f3e0df379a0ae263dcefb5f72a80a5"
BASE = "sha256:aafbad31e766488bbfd0709a5b12798677505c8bae3cc7b957405b0b16ecee03"
PINS = {
    "plan.json": "0763dd582933da18e20b7bf879a37c96bb6414faf8ab66cade8bc2b02a855b28",
    "selection.json": "654a411f16b7607c9ddd40d6a4d0c8dcdb9ec8b2c6b1f20eac5a5070808ca180",
    "test-report.json": "f323186fee013a3c55acac9e061500c2245c36976db01495a86f48a83c57392b",
}


def sha(content):
    return hashlib.sha256(content).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def write(path, content):
    """Exclusive owned outputs only; never replace a previous attempt."""
    with path.open("xb") as target:
        target.write(content)
    path.chmod(0o600)


def write_json(path, value):
    write(path, json.dumps(value, indent=2, sort_keys=True, allow_nan=False).encode() + b"\n")


def archive_files(content):
    """Read bounded regular members without tar extraction or link traversal."""
    result = {}
    total = 0
    with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as archive:
        for member in archive:
            path = PurePosixPath(member.name)
            require(not path.is_absolute() and ".." not in path.parts
                    and path.parts[0] == "emulation", "unsafe archive path")
            require(member.isdir() or member.isfile(), "archive links/devices forbidden")
            if member.isdir():
                continue
            require(str(path) not in result and 0 <= member.size <= 8 * 1024**2,
                    "duplicate or oversized archive member")
            total += member.size
            require(total <= 32 * 1024**2, "archive exceeds recovery bound")
            result[str(path)] = archive.extractfile(member).read()
    return result


def audit():
    bundle = CHECKPOINT.read_bytes()
    require(sha(bundle) == CHECKPOINT_HASH, "checkpoint pin mismatch")
    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        require(sha(archive.read("weights.pt")) == manifest["weights_sha256"], "weights mismatch")
    content = ARCHIVE.read_bytes()
    require(sha(content) == ARCHIVE_HASH, "archive pin mismatch")
    files = archive_files(content)
    spec = manifest["environment_spec"]
    require(sha(canonical(spec)) == manifest["spec_hash"], "spec mismatch")
    require(sha(canonical(spec["source_files"])) == spec["source_sha256"], "source-map mismatch")
    for name, expected in spec["source_files"].items():
        require(sha(files["emulation/" + name]) == expected, "archived lab mismatch: " + name)
    sources = {p.name: sha(p.read_bytes()) for p in (TRAIN / "source").glob("*.py")}
    require(sources == manifest["client_source_files"], "frozen client mismatch")
    for name, expected in PINS.items():
        require(sha((HOLDOUT / name).read_bytes()) == expected, "benchmark pin mismatch: " + name)
    plan = json.loads((HOLDOUT / "plan.json").read_bytes())
    sessions = []
    for policy in plan["policy_order"]:
        directory = HOLDOUT / ("test-" + policy)
        summary = json.loads((directory / "summary.json").read_bytes())
        require(sha((directory / "evidence.jsonl").read_bytes()) == summary["evidence_sha256"],
                "raw evidence mismatch: " + policy)
        require(summary["environment_spec"] == spec and summary["lab_provenance"] == manifest["lab_provenance"],
                "historical raw spec/provenance mismatch: " + policy)
        sessions.append({"policy": policy, "evidence_sha256": summary["evidence_sha256"]})
    return manifest, files, {
        "version": "nanfo.adr024-runtime-recovery/v1", "checkpoint_sha256": CHECKPOINT_HASH,
        "archive_sha256": ARCHIVE_HASH, "spec_sha256": manifest["spec_hash"],
        "lab_source_sha256": spec["source_sha256"], "lab_source_files": spec["source_files"],
        "client_source_files": sources, "client_source_sha256": sha(canonical(sources)),
        "runtime_versions": manifest["versions"], "contract_sha256": manifest["contract_hash"],
        "historical_image_id": manifest["lab_provenance"]["lab_image_id"],
        "environment_version": spec["version"], "historical_sessions": sessions,
        "dependency_locks": {name: sha((TRAIN / "source" / name).read_bytes())
                             for name in ("pyproject.toml", "uv.lock")},
        "archive_all_files": {name: sha(value) for name, value in files.items()},
        "live_qualified": False, "measurements_started": False, "training_started": False,
    }


def registry_template(manifest):
    def ref(path):
        content = (AI / path).read_bytes()
        return {"path": path, "sha256": sha(content), "size_bytes": len(content)}

    prefix = "artifacts/adr014-holdout-001"
    plan = json.loads((HOLDOUT / "plan.json").read_bytes())
    return dict(version=1, model_id="adr014-incumbent",
                checkpoint=ref("artifacts/adr014-001/train-06/checkpoint.ptz"),
                source_directory="artifacts/adr014-001/source",
                source_sha256=manifest["client_source_files"], contract_sha256=manifest["contract_hash"],
                spec_sha256=manifest["spec_hash"], runtime_versions=manifest["versions"],
                observation_contract="nanfo.passive-measured-v4.v1", runtime_action="linux-frr-host-route",
                action_ids=["route0", "route1"],
                scopes=[dict(network_id="REPLACE_NETWORK_UUID", workspace_id="REPLACE_WORKSPACE_UUID",
                             snapshot_path="snapshot.json")],
                installed_at="REPLACE_AWARE_INSTALL_TIME", expires_at="REPLACE_AWARE_EXPIRY",
                max_observation_age_seconds=30, plan=ref(prefix + "/plan.json"),
                selection=ref(prefix + "/selection.json"), report=ref(prefix + "/test-report.json"),
                sessions=[dict(summary=ref(f"{prefix}/test-{p}/summary.json"),
                               evidence=ref(f"{prefix}/test-{p}/evidence.jsonl")) for p in plan["policy_order"]])


def command(stage, label, args, *, timeout=120, check=True):
    result = subprocess.run(args, cwd=ROOT, capture_output=True, timeout=timeout)
    write(stage / (label + ".stdout"), result.stdout)
    write(stage / (label + ".stderr"), result.stderr)
    write_json(stage / (label + ".command.json"), {"argv": args, "returncode": result.returncode})
    require(not check or result.returncode == 0, "command failed; preserved logs: " + label)
    return result


PROBE = """
import hashlib, importlib.metadata, json, platform, subprocess
from emulation.experiment import environmentSpec
spec, digest = environmentSpec('matched')
print(json.dumps(dict(spec=spec, spec_sha256=digest, python=platform.python_version(),
    packages={d.metadata['Name'].lower():d.version for d in importlib.metadata.distributions()},
    dpkg=subprocess.check_output(['dpkg-query','-W','-f=${Package}=${Version}\\n']).decode()),sort_keys=True))
"""


def static_probe(stage, image, label):
    name = "nanfo-adr024-recover-" + uuid.uuid4().hex
    result = command(stage, label + "-create", ["docker", "create", "--name", name,
        "--label", "nanfo.adr024.role=runtime-recovery", "--network", "none", "--read-only",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--pids-limit", "64",
        "--memory", "512m", "--cpus", "1", "--entrypoint", "python", image, "-B", "-c", PROBE])
    container = result.stdout.decode().strip()
    require(bool(re.fullmatch(r"[a-f0-9]{64}", container)), "invalid created container ID")
    try:
        result = command(stage, label + "-probe", ["docker", "start", "-a", container])
        state = command(stage, label + "-state", ["docker", "inspect", "--format", "{{json .State}}", container])
        require(json.loads(state.stdout)["ExitCode"] == 0, "static probe failed")
        return json.loads(result.stdout)
    finally:
        command(stage, label + "-cleanup", ["docker", "rm", container])


def verify_dependencies(probe, files):
    require(probe["python"] == "3.9.23", "lab Python differs from archived Dockerfile")
    requirements = files["emulation/requirements.txt"].decode().splitlines()
    for row in requirements + ["pip==23.2.1", "setuptools==57.5.0", "wheel==0.37.1"]:
        if not row or row.startswith("#"):
            continue
        name, version = row.split("==")
        require(probe["packages"].get(name.lower()) == version, "base dependency mismatch: " + name)
    installed = dict(row.split("=", 1) for row in probe["dpkg"].splitlines())
    for name, version in {"mininet": "2.3.0-1", "openvswitch-switch": "2.15.0+ds1-2+deb11u5",
                          "frr": "7.5.1-1.1+deb11u2"}.items():
        require(installed.get(name) == version, "base system dependency mismatch: " + name)


def prepare(build=False):
    manifest, files, report = audit()
    stage = Path(tempfile.mkdtemp(prefix="nanfo-adr024-runtime-", dir="/tmp/opencode"))
    print("recovery_stage=" + str(stage), flush=True)
    write_json(stage / "audit.json", report)
    for name, content in files.items():
        path = stage / name
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        write(path, content)
    source = stage / "nanfo_routing"
    source.mkdir(mode=0o700)
    for path in sorted((TRAIN / "source").iterdir()):
        if path.name in manifest["client_source_files"] or path.name in ("pyproject.toml", "uv.lock"):
            write(source / path.name, path.read_bytes())
    write_json(stage / "registry.template.json", registry_template(manifest))
    historical = command(stage, "historical-image", ["docker", "image", "inspect", report["historical_image_id"]], check=False)
    report["historical_image_present"] = historical.returncode == 0
    # Record each committed snapshot without checking out or overwriting the worktree.
    history = command(stage, "git-history", ["git", "log", "--all", "--format=%H", "--", "emulation/experiment.py"])
    matches = {}
    for revision in history.stdout.decode().splitlines():
        matched = []
        for name, expected in report["lab_source_files"].items():
            result = subprocess.run(["git", "show", f"{revision}:emulation/{name}"], cwd=ROOT, capture_output=True)
            if result.returncode == 0 and sha(result.stdout) == expected:
                matched.append(name)
        matches[revision] = matched
    report["git_snapshot_matches"] = matches
    if build:
        base = static_probe(stage, BASE, "base")
        verify_dependencies(base, files)
        write_json(stage / "base-dependencies.json", base)
        # Use inherited exact dependencies; replace only this new image's source tree.
        # Keep the archived hashed Dockerfile INSIDE emulation, separate from this recipe.
        recipe = (f"FROM {BASE}\n"
                  "RUN rm -rf /opt/nanfo/emulation\n"
                  "COPY emulation/ /opt/nanfo/emulation/\n"
                  "RUN python -m pip check && python -B -m unittest discover -s emulation/tests -v\n"
                  'LABEL nanfo.adr024.role="source-matched-evaluation-only"\n')
        write(stage / "Dockerfile.recovery", recipe.encode())
        write(stage / ".dockerignore", b"*\n!emulation/\n!emulation/**\n!Dockerfile.recovery\n")
        tag = "nanfo-adr024-v4-evaluation:" + uuid.uuid4().hex
        command(stage, "build", ["docker", "build", "--pull=false", "--network=none", "--tag", tag,
                "--file", str(stage / "Dockerfile.recovery"), str(stage)], timeout=300)
        result = command(stage, "rebuilt-image", ["docker", "image", "inspect", tag])
        identity = json.loads(result.stdout)[0]["Id"]
        rebuilt = static_probe(stage, identity, "rebuilt")
        require(rebuilt["spec"] == manifest["environment_spec"] and rebuilt["spec_sha256"] == manifest["spec_hash"],
                "rebuilt environment differs from frozen spec")
        require(all(rebuilt[key] == base[key] for key in ("python", "packages", "dpkg")), "dependencies changed")
        report.update(rebuilt_image_id=identity, rebuilt_tag=tag, inherited_base_image_id=BASE,
                      rebuilt_spec_exact=True, dependencies_inherited_exact=True,
                      historical_image_identity_reproduced=identity == report["historical_image_id"])
        result = command(stage, "validator-boundaries", [str(AI / ".venv/bin/python"), "-B", str(Path(__file__).resolve()),
                "boundaries", "--image-id", identity], timeout=120)
        report["validator_boundaries"] = json.loads(result.stdout)
    write_json(stage / "recovery.json", report)
    return report


def boundaries(image):
    """Historical read-only diagnostic; altered copies are tests, never measurements."""
    require(bool(re.fullmatch(r"sha256:[a-f0-9]{64}", image)), "invalid image identity")
    manifest, _, _ = audit()
    require(image != manifest["lab_provenance"]["lab_image_id"], "boundary test requires distinct image")
    source = TRAIN / "source"
    name = "_adr024_original"
    spec = importlib.util.spec_from_file_location(name, source / "__init__.py", submodule_search_locations=[str(source)])
    package = importlib.util.module_from_spec(spec)
    sys.modules[name] = package
    spec.loader.exec_module(package)
    cli = importlib.import_module(name + ".cli")
    artifacts = importlib.import_module(name + ".artifacts")
    evidence = importlib.import_module(name + ".evidence")
    contracts = importlib.import_module(name + ".contracts")
    _, actual = artifacts.loadCheckpoint(CHECKPOINT)
    require(actual.model_dump() == manifest, "original checkpoint loader differs")
    history = json.loads((TRAIN / "validation-06/last-history.json").read_bytes())
    result = {"evidence_kind": "historical-replay-and-mutated-unit-copies-not-live", "cases": {}}
    with tempfile.TemporaryDirectory(prefix="adr024-boundary-", dir="/tmp/opencode") as directory:
        path = Path(directory) / "history.json"
        for case in ("original", "rebuilt_image", "wrong_source", "wrong_spec"):
            copy = json.loads(json.dumps(history))
            raw = copy["frames"][0]["response"]["data"]["evidence"]
            if case == "rebuilt_image":
                raw["provenance"]["lab_image_id"] = image
                frame = copy["frames"][0]
                # The measurement parser accepts a correctly shaped, distinct image
                # identity; inference's original exact-provenance check must reject it.
                require(evidence.validateMeasurement(contracts.Response.model_validate(frame["response"]).data,
                        contracts.Request.model_validate(frame["request"])) == manifest["environment_spec"],
                        "rebuilt identity unexpectedly changed measurement semantics")
            elif case == "wrong_source":
                raw["provenance"]["source_sha256"] = "0" * 64
            elif case == "wrong_spec":
                raw["environment_spec"]["version"] = 5
            path.write_bytes(canonical(copy))
            stdout, stderr = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = cli.main(["infer", "--checkpoint", str(CHECKPOINT), "--history", str(path)])
            require((code == 0) == (case == "original"), "unexpected inference boundary: " + case)
            result["cases"][case] = {"returncode": code, "stderr": stderr.getvalue(),
                                      "stdout": stdout.getvalue()}
    require("inference image/source provenance differs from checkpoint" in result["cases"]["rebuilt_image"]["stderr"],
            "image mismatch must hit original provenance check")
    result["rebuilt_live_inference_compatible"] = False
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("audit", "prepare", "build", "boundaries"))
    parser.add_argument("--image-id")
    args = parser.parse_args()
    os.umask(0o077)
    try:
        if args.operation == "audit":
            result = audit()[2]
        elif args.operation == "boundaries":
            result = boundaries(args.image_id or "")
        else:
            result = prepare(build=args.operation == "build")
        print(json.dumps(result, indent=2, sort_keys=True))
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print("runtime recovery failed: " + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

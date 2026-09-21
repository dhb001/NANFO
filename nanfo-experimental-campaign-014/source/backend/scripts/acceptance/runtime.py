"""Bounded process groups and Docker inspection without secret-bearing inspect data."""

import json
import os
import selectors
import signal
import subprocess
import time

from scripts.acceptance.common import Blocked, ID, OWNER_LABEL, STAGE_LABEL, encoded, owned, sha

PRESERVABLE_ID = "1db3c959ff4f712da1d9f5674c120c900f7d5392d2236f6f3d41f68f3620ac55"
PRESERVABLE_NAME = "nanfo-emulation-lab-1"


def execute(argv, *, timeout, cwd=None, env=None):
    """Drain both streams with a fixed retained bound; never persist raw diagnostics."""
    process = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    deadline = time.monotonic() + timeout
    chunks = {"stdout": bytearray(), "stderr": bytearray()}
    counts = {"stdout": 0, "stderr": 0}
    timed_out = False
    try:
        with selectors.DefaultSelector() as selector:
            for name, stream in (("stdout", process.stdout), ("stderr", process.stderr)):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, name)
            while selector.get_map():
                if time.monotonic() >= deadline:
                    timed_out = True
                    break
                for key, _ in selector.select(min(0.1, max(0, deadline - time.monotonic()))):
                    data = os.read(key.fileobj.fileno(), 8192)
                    if not data:
                        selector.unregister(key.fileobj)
                        continue
                    counts[key.data] += len(data)
                    chunks[key.data].extend(data[:max(0, 1024 * 1024 - len(chunks[key.data]))])
            if not timed_out:
                try:
                    process.wait(timeout=max(0.01, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    timed_out = True
    finally:
        # Kill the entire owned session even if its leader exited leaving children.
        for sig in (signal.SIGCONT, signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(process.pid, sig)
            except ProcessLookupError:
                pass
        process.wait(timeout=3)
        process.stdout.close()
        process.stderr.close()
    return {"returncode": process.returncode, "timed_out": timed_out,
            "stdout": bytes(chunks["stdout"]), "stderr": bytes(chunks["stderr"]), "bytes": counts}


def docker(*args, timeout=10):
    result = execute(["docker", *args], timeout=timeout)
    if result["timed_out"] or result["returncode"] or result["bytes"]["stdout"] > 1024 * 1024:
        raise Blocked("docker_inspection_or_operation_failed")
    return result["stdout"].decode()


def snapshot(timeout=10):
    # Never inspect Config.Env, command lines, or mounts containing secrets.
    identities = docker("ps", "-a", "-q", "--no-trunc", timeout=timeout).split()
    if not identities:
        return {}
    if len(identities) > 256 or any(not ID.fullmatch(identity) for identity in identities):
        raise Blocked("docker_inventory_bound_or_identity")
    lines = docker("inspect", "--format",
                   '{"Id":{{json .Id}},"Name":{{json .Name}},"Image":{{json .Image}},'
                   '"State":{{json .State.Status}},"Labels":{{json .Config.Labels}},'
                   '"Privileged":{{json .HostConfig.Privileged}}}', *identities, timeout=timeout)
    rows = {}
    for line in lines.splitlines():
        row = json.loads(line)
        identity = row["Id"]
        if not ID.fullmatch(identity):
            raise Blocked("docker_identity_invalid")
        row["Name"] = row["Name"].lstrip("/")
        row["Labels"] = {key: value for key, value in (row["Labels"] or {}).items()
                         if key in {OWNER_LABEL, STAGE_LABEL, "com.docker.compose.project", "com.docker.compose.service"}}
        rows[identity] = row
        if identity == PRESERVABLE_ID:
            # Full inspect includes state, mounts, image and configuration. Only
            # its hash leaves memory; no credential-bearing fields are published.
            complete = json.loads(docker("inspect", identity, timeout=timeout))[0]
            # Docker emits this set in nondeterministic order. Preserve every
            # mount field while canonicalizing by destination, not inspection order.
            complete["Mounts"] = sorted(complete.get("Mounts", []), key=lambda mount: mount["Destination"])
            row["InspectSHA256"] = sha(encoded(complete))
    return rows


def baseline_safe(rows, services, processes, preserve_stopped=()):
    if any(identity != PRESERVABLE_ID for identity in preserve_stopped):
        raise Blocked("unapproved_preserve_exception")
    for identity in preserve_stopped:
        row = rows.get(identity, {})
        if row.get("Name") != PRESERVABLE_NAME or row.get("State") != "exited" or not row.get("InspectSHA256"):
            raise Blocked("preserved_container_missing_running_or_invalid")
    for row in rows.values():
        if row["Id"] in preserve_stopped:
            continue
        labels = row["Labels"]
        if row.get("Privileged"):
            raise Blocked("existing_privileged_container_preserved")
        text = " ".join((row["Name"], row["Image"], labels.get("com.docker.compose.project", ""))).lower()
        if ("nanfo" in text and any(word in text for word in
                ("lab", "emulation", "experiment", "training", "refinement", "execution", "override", "acceptance", "report"))):
            raise Blocked("existing_lab_or_verifier_container")
    for text in (services, processes):
        if any(word in text.lower() for word in (
            "nanfo-training", "nanfo-refinement", "emulation.runner", "experiment-start",
            "verify_execution.py", "verify_operator_override.py", "verify_emulation.py",
            "uvicorn", "gunicorn", "train_measured", "campaign_runner",
        )):
            raise Blocked("active_training_lab_or_backend_process")


def cleanup(stage_dir, owner, stage, before):
    from scripts.acceptance.common import read_json, write_new

    deadline = time.monotonic() + 90

    def budget():
        remaining = deadline - time.monotonic()
        if remaining <= 1:
            raise Blocked("cleanup_deadline_unknown_resources_preserved")
        return min(5, remaining / 2)

    names = set()
    for path in stage_dir.glob("owned-*.json"):
        value, _ = read_json(path)
        if value.get("owner") == owner and value.get("stage") == stage:
            names.add(value["name"])
    current = snapshot(timeout=budget())
    removed = []
    for identity, row in current.items():
        if owned(row, owner=owner, stage=stage, baseline=before, names=names):
            # Re-inspect exact ID immediately before deletion; never remove by prefix/name.
            again = snapshot(timeout=budget()).get(identity)
            if again and owned(again, owner=owner, stage=stage, baseline=before, names=names):
                docker("rm", "-f", "-v", identity, timeout=budget())
                removed.append(identity)
    after = snapshot(timeout=budget())
    write_new(stage_dir / "baseline-after.json", after)
    leaked = [identity for identity, row in after.items()
              if (row["Labels"].get(OWNER_LABEL) == owner and row["Labels"].get(STAGE_LABEL) == stage)
              or row["Name"] in names]
    drift = [identity for identity in before if after.get(identity) != before[identity]]
    unknown = [identity for identity in after if identity not in before and identity not in removed]
    # The killed verifier cannot unlink these two known private credentials. Never
    # traverse or recursively remove work/evidence directories (some are root-owned).
    for filename in ("redis.conf", "infrastructure-redis.conf", "pytest-private.xml"):
        path = stage_dir / "work" / filename
        if path.parent.is_dir() and not path.parent.is_symlink():
            path.unlink(missing_ok=True)
    return {"passed": not leaked and not drift and not unknown, "removed_ids": removed,
            "leaked_ids": leaked, "baseline_changed_ids": drift, "unknown_new_ids": unknown}

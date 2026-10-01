"""ADR024 operator evaluation producer with explicit before-reset/frame barriers.

No training. Frozen modules/transport/measurement validation remain unchanged.
The separate backend acceptance coordinator releases each barrier after read-only
provider decisions, never passes model recommendations as experiment actions.
"""

import argparse
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import time

PIN = re.compile(r"[a-f0-9]{64}")
SOURCE_NAME = re.compile(r"[a-z_]+\.py")
MAX_SOURCE_BYTES = 1024 * 1024
MAX_CHECKPOINT_BYTES = 16 * 1024 * 1024


def read_once(path, limit):
    """One bounded read of a regular file; a final symlink or FIFO is refused."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("frozen_input_not_regular")
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError("frozen_input_too_large")
    return data


def verified_snapshot(plan, destination):
    """Copy only pin-verified bytes; nothing named by the plan is executed or loaded in place."""
    source, pins = Path(plan["source_directory"]), plan["client_source_sha256"]
    if type(pins) is not dict or not pins or any(
            not SOURCE_NAME.fullmatch(name) or type(pin) is not str or not PIN.fullmatch(pin)
            for name, pin in pins.items()):
        raise ValueError("frozen_source_pins_invalid")
    if {path.name for path in source.glob("*.py")} != set(pins):
        raise ValueError("frozen_source_inventory_changed")
    package = destination / "source"
    package.mkdir(mode=0o700)
    for name, pin in sorted(pins.items()):
        data = read_once(source / name, MAX_SOURCE_BYTES)
        if hashlib.sha256(data).hexdigest() != pin:
            raise ValueError("frozen_source_changed")
        (package / name).write_bytes(data)
    data = read_once(Path(plan["checkpoint"]), MAX_CHECKPOINT_BYTES)
    pin = plan.get("checkpoint_sha256")
    if type(pin) is not str or not PIN.fullmatch(pin) or hashlib.sha256(data).hexdigest() != pin:
        raise ValueError("checkpoint_pin_mismatch")
    checkpoint = destination / "checkpoint.ptz"
    checkpoint.write_bytes(data)
    return package, checkpoint


def modules(source):
    alias = "_live_acceptance_frozen"
    spec = importlib.util.spec_from_file_location(alias, source / "__init__.py",
                                                 submodule_search_locations=[str(source)])
    package = importlib.util.module_from_spec(spec)
    sys.modules[alias] = package
    spec.loader.exec_module(package)
    return {name: importlib.import_module(alias + "." + name)
            for name in ("artifacts", "cli", "contracts", "env", "transport")}


def write(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())


def wait(path, deadline):
    while not path.exists():
        if time.monotonic() > deadline:
            raise TimeoutError("evaluation_barrier_expired")
        time.sleep(.05)


def run(args):
    os.umask(0o077)
    plan_bytes = args.plan.read_bytes()
    plan = json.loads(plan_bytes)
    item = next(row for row in plan["episodes"] if row["scenario"] == args.scenario)
    with tempfile.TemporaryDirectory(prefix="nanfo-live-feed-frozen-") as private:
        source, checkpoint = verified_snapshot(plan, Path(private))
        m = modules(source)
        a = m["artifacts"]
        # The frozen loader's own torch.load(weights_only=True) reads the pin-verified copy.
        _, manifest = a.loadCheckpoint(checkpoint)
        if a.clientSources() != plan["client_source_sha256"]:
            raise ValueError("frozen_source_changed")
        evaluate(args, plan_bytes, item, m, manifest)


def evaluate(args, plan_bytes, item, m, manifest):
    a = m["artifacts"]
    args.output.mkdir(mode=0o700)
    log = a.EvidenceLog(args.output / "evidence.jsonl")
    env = m["env"].RoutingEnv(m["cli"].LoggedTransport(m["transport"].DockerTransport(args.container, 90), log),
        split="train", scenario=args.scenario, mode="matched", window_seconds=2., episode_steps=4,
        expectedSpec=manifest.environment_spec)
    log.append(dict(kind="session", summary=dict(kind="evaluation", mode="matched", generalization=False,
        window_seconds=2., episode_steps=4, split="train", evaluation_role="operational-not-held-out",
        seeds=[item["seed"]], scenarios=[args.scenario], policy="constant0",
        plan_sha256=hashlib.sha256(plan_bytes).hexdigest())))
    write(args.output / "header-ready.json", {"session_sha256": hashlib.sha256(
        (args.output / "evidence.jsonl").read_bytes().rstrip(b"\n")).hexdigest()})
    deadline = time.monotonic() + 240
    try:
        wait(args.output / "release-reset", deadline)
        env.reset(seed=item["seed"])
        if env.labProvenance != manifest.lab_provenance:
            raise ValueError("actual_runtime_mismatch")
        write(args.output / "frame-0.json", {"acquired_unix": time.time(), "scenario": args.scenario,
                                             "episode_id": env.data.episode_id})
        for index in range(1, 3):
            wait(args.output / f"release-step-{index}", deadline)
            _, _, _, _, info = env.step(0)  # preregistered fixed action, never recommendation dispatch
            if not info["valid_transition"]:
                raise ValueError("operational_measurement_invalid")
            write(args.output / f"frame-{index}.json", {"acquired_unix": time.time(), "scenario": args.scenario})
        wait(args.output / "release-close", deadline)
    finally:
        env.close()
        log.close()
        write(args.output / "closed.json", {"cleanup_acknowledged": True, "evidence_sha256": log.digest.hexdigest(),
                                          "training": False, "recommendations_applied": False})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scenario", choices=("path0", "path1"), required=True)
    parser.add_argument("--container", required=True)
    run(parser.parse_args())

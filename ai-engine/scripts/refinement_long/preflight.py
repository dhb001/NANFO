"""Inventory historical artifacts and all prior measured/attempted seed evidence."""

import hashlib
import json
import stat
import time
import uuid
from pathlib import Path

from contract import declaration
from history import IMAGE, OLD, PARENT_HASH, PREVIOUS, ROOT, a, c, digest, parent, read

OUTPUT = ROOT / "artifacts/adr016-001"
SCRIPT_DIR = Path(__file__).resolve().parent


def sources():
    return {
        str(p.relative_to(ROOT)): digest(p)
        for directory in (SCRIPT_DIR, ROOT / "scripts/refinement", ROOT / "src/nanfo_routing")
        for p in sorted(directory.glob("*.py"))
    }


def preservation():
    previous = read(PREVIOUS / "plan.json")["parent_preservation"]
    for name, sha in previous.items():
        if digest(ROOT / name) != sha:
            raise ValueError("original1437 incumbent inventory changed")
    result = dict(previous)
    for directory in (ROOT / "artifacts/adr015-001", PREVIOUS):
        for path in sorted(directory.rglob("*")):
            if path.is_file():
                if path.is_symlink():
                    raise ValueError("symlink in historical evidence")
                result[str(path.relative_to(ROOT))] = digest(path)
    for path in (ROOT / "artifacts/adr015-release.json",):
        result[str(path.relative_to(ROOT))] = digest(path)
    items = list(result.items())
    return [dict(items[i : i + 1024]) for i in range(0, len(items), 1024)]


def seedsIn(value):
    """Read seed identity fields only; never interpret archived metrics as training data."""
    result = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "seed" and type(item) is int:
                result.add(item)
                if type(value.get("episodes")) is int:
                    result.update(range(item, item + value["episodes"]))
            elif key in ("seeds", "training_seeds") and isinstance(item, list):
                result.update(s for s in item if type(s) is int)
            elif isinstance(item, (dict, list)):
                result.update(seedsIn(item))
    elif isinstance(value, list):
        for item in value:
            result.update(seedsIn(item))
    return result


def priorSeeds():
    used, inventory = set(), {}
    # Include failed raw frames and instrumentation, not just successful summaries.
    for base in (
        ROOT / "artifacts",
        ROOT.parent / "emulation/output",
        ROOT.parent / "emulation/results",
    ):
        for path in sorted(base.rglob("*")):
            if (
                OUTPUT in path.parents
                or not path.is_file()
                or path.suffix not in (".json", ".jsonl")
            ):
                continue
            if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode):
                raise ValueError("unsafe prior evidence path")
            # A plan's reserved future namespace is not a measured seed. Attempt
            # ledgers do count reservations conservatively, including failed runs.
            if "plan" in path.name and "collection" not in path.name:
                continue
            if path.stat().st_size > 64 * 1024**2:
                raise ValueError("prior evidence exceeds audit bound")
            found = set()
            with path.open("rb") as source:
                if path.suffix == ".jsonl":
                    for line in source:
                        if len(line) > 2 * 1024**2:
                            raise ValueError("oversized prior raw frame")
                        found.update(seedsIn(json.loads(line)))
                else:
                    found.update(seedsIn(json.load(source)))
            if found:
                inventory[str(path)] = {"sha256": digest(path), "seeds": sorted(found)}
                used.update(found)
    chosen = {
        r["seed"] for split in ("training", "validation", "test") for r in declaration()[split]
    }
    if chosen & used:
        raise ValueError(f"chosen seeds already used/reserved: {sorted(chosen & used)}")
    if not any("adr015-002/ledger.json" in p for p in inventory):
        raise ValueError("completed ADR015 ledger missing")
    items = list(inventory.items())
    return {
        "sources": [dict(items[i : i + 1024]) for i in range(0, len(items), 1024)],
        "used_seeds": sorted(used),
        "overlap": [],
    }


def prepare():
    _, metadata = parent()
    status = read(PREVIOUS / "status.json")
    if status["state"] != "stopped" or status["container_id"] is not None:
        raise ValueError("ADR015 must be terminal and cleaned up")
    release = OLD["campaign"].release(ROOT / "artifacts/adr015-release.json")
    if release["image_id"] != IMAGE:
        raise ValueError("ADR016 must use unchanged pinned V5 image")
    result = {
        **declaration(),
        "output": str(OUTPUT),
        "campaign_id": uuid.uuid4().hex,
        "release": release,
        "image_id": IMAGE,
        "sources": sources(),
        "runtime_versions": a.runtimeVersions(),
        "preservation": preservation(),
        "prior_seed_audit": priorSeeds(),
        "parent_checkpoint_sha256": PARENT_HASH,
        "parent_manifest_sha256": hashlib.sha256(c.jsonBytes(metadata)).hexdigest(),
    }
    # Clock begins after bounded read-only preparation, before measurement/startup.
    result["started_unix"] = time.time()
    return result

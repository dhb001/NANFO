"""Read-only independent V5 instrumentation validation before campaign admission."""

import argparse
import json
from pathlib import Path

from campaign import read
from evidence import Request, phase, validate
from frozen import ROOT, digest
from plan import PROFILES


def inspect(directory):
    plan = read(directory / "plan.json")
    release = {
        "environment_spec": plan["environment_spec"],
        "spec_hash": plan["spec_hash"],
        "image_id": plan["image_id"],
    }
    result = {
        "valid_windows": 0,
        "profiles": {},
        "failures": [],
        "source": str(directory),
        "instrumentation_only": True,
        "not_training_data": True,
    }
    for path in sorted(directory.glob("experiment-*.json")):
        if path.name.endswith("-schedule.json"):
            continue
        data = read(path)
        # Producer disk records are data objects, not a transport envelope.
        if data.get("scenario") not in PROFILES:
            continue
        index = data["step_index"]
        request = Request(
            command="reset" if index == 0 else "step",
            seed=data["seed"],
            scenario=data["scenario"],
            mode=data["mode"],
            episode_id=data["episode_id"] if index else None,
            step_index=index if index else None,
            action=(1 if index == 1 else 0) if index else None,
            window_seconds=2.0,
            episode_steps=2,
        )
        try:
            validate(
                {"version": 1, "ok": True, "error": None, "data": data},
                request,
                release,
                phase(data["seed"], data["scenario"], index, plan["environment_spec"]),
            )
            result["valid_windows"] += 1
            key = data["mode"] + ":" + data["scenario"]
            result["profiles"][key] = result["profiles"].get(key, 0) + 1
        except (ValueError, KeyError, TypeError) as exc:
            result["failures"].append(
                {"path": path.name, "sha256": digest(path), "error": str(exc)}
            )
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    if not args.directory.resolve().is_relative_to(ROOT.parent / "emulation/output"):
        parser.error("only lab instrumentation output is accepted")
    print(json.dumps(inspect(args.directory)))

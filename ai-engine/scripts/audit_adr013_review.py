"""Read-only historical fingerprints/gate replay plus current seeded-evidence audit."""

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

from nanfo_routing.artifacts import loadCheckpoint
from nanfo_routing.cli import report
from nanfo_routing.contracts import parseJson


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    root = args.output.resolve()
    hashes = parseJson((root / "artifact-hashes.json").read_bytes())
    for name, digest in hashes.items():
        path = root / name
        if not path.resolve().is_relative_to(root) or path.is_symlink():
            raise ValueError("unsafe artifact path")
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError(f"historical artifact fingerprint changed: {name}")
    summaries = sorted(root.glob("*/summary.json"))
    current = report(summaries)
    windows = sum(len(row["reconstructed_phases"]) for row in current["sessions"])

    # Audit-only isolated package namespace, no compatibility fallback in production.
    # Do not create __pycache__ inside the historical source snapshot.
    sys.dont_write_bytecode = True
    source = root / "frozen-client-source"
    package = "nanfo_historical_review"
    spec = importlib.util.spec_from_file_location(
        package, source / "__init__.py", submodule_search_locations=[str(source)]
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[package] = module
    spec.loader.exec_module(module)
    from importlib import import_module

    old = import_module(f"{package}.qualification")
    results = []
    for path in sorted(root.glob("qualification-*.json")):
        saved = parseJson(path.read_bytes())
        paths = saved["evidence_paths"]
        replay = old.qualify(
            Path(paths["checkpoint"]),
            Path(paths["training"]),
            [Path(item) for item in paths["validation"]],
            Path(paths["plan"]),
            [Path(item) for item in paths["calibration"]],
        )
        if replay != saved:
            raise ValueError("historical qualification gate replay differs")
        try:
            loadCheckpoint(Path(paths["checkpoint"]))
        except ValueError as exc:
            if "client source differs" not in str(exc):
                raise
        else:
            raise ValueError("current runtime unexpectedly accepted old source binding")
        results.append(
            {
                "artifact": path.name,
                "gate_replay_exact": True,
                "qualified": saved["qualified"],
                "current_source_drift_rejected": True,
            }
        )
    print(
        json.dumps(
            {
                "historical_fingerprints_verified": len(hashes),
                "current_seeded_validator_accepted_windows": windows,
                "historical_gate_replays": results,
                "artifact_writes": False,
                "live_collection": False,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

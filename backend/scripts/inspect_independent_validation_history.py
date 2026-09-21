"""Read-only inventory of historical measured raw evidence; no recertification."""

import argparse
import hashlib
import json

from app.modules.autonomy.artifact_io import ArtifactStore, EvidenceError, parse_json


def inspect(store: ArtifactStore, path: str) -> dict:
    content = store.read(path, limit=64 * 1024 * 1024)
    document = parse_json(content)
    specs, queue_paths, native_paths = [], [], []

    def visit(value, prefix=""):
        if isinstance(value, dict):
            for key, child in value.items():
                current = f"{prefix}.{key}" if prefix else key
                if key in ("queue_interval", "counter_interval", "observability", "control_version"):
                    specs.append({"path": current, "value": child})
                if "queue" in key or "backlog" in key:
                    queue_paths.append(current)
                if "raw" in key or key in ("stdout", "stderr"):
                    native_paths.append(current)
                visit(child, current)
        elif isinstance(value, list):
            for i, child in enumerate(value):
                visit(child, f"{prefix}[{i}]")
    visit(document)
    return {"path": path, "sha256": hashlib.sha256(content).hexdigest(), "size_bytes": len(content),
            "recorded_contract": specs[:100], "queue_fields": queue_paths[:100], "native_fields": native_paths[:100],
            "physical_qualified": False, "importable_without_new_evidence": False,
            "required_new_evidence": ["externally preregistered independent groups", "authenticated byte endpoint queues",
                                      "same-window per-demand arrivals/departures/drops", "old/new action timing and transitions",
                                      "reviewed within-interval service and error guarantee", "explicit scoped installation"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--path", required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(inspect(ArtifactStore(args.root), args.path), sort_keys=True))
        return 0
    except EvidenceError as exc:
        print(json.dumps({"reason": str(exc), "physical_qualified": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

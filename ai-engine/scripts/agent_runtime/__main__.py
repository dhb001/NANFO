"""Run from ai-engine/scripts: python -B -m agent_runtime --help."""

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

from shadow.io import parseJson, readPinned

from .contracts import Request
from .memory import Memory
from .registry import authorize, loadRegistry
from .runtime import EvidenceFiles, analyze, runOnce


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=("ingest", "retrieve", "analyze", "run-once", "export", "audit")
    )
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--registry-sha256", required=True)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--request-sha256", required=True)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--after", type=int, default=0)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--plan-sha256")
    parser.add_argument("--diagnostic", type=Path)
    parser.add_argument("--outcomes", type=Path)
    parser.add_argument("--benchmark", type=Path)
    args = parser.parse_args(argv)
    store = None
    try:
        registry = loadRegistry(args.registry, args.registry_sha256)
        request = Request.model_validate_json(
            json.dumps(parseJson(readPinned(args.request, args.request_sha256, limit=65536)))
        )
        permission = {
            "ingest": "memory_write",
            "retrieve": "memory_read",
            "run-once": "run",
            "audit": "export",
        }.get(args.command, args.command)
        authorize(registry, request.scope, permission, time.time())
        if args.command in ("analyze", "run-once"):
            if not all(
                (args.plan, args.plan_sha256, args.diagnostic, args.outcomes, args.benchmark)
            ):
                raise ValueError("evidence_files_required")
            evidence = EvidenceFiles(
                args.plan, args.plan_sha256, args.diagnostic, args.outcomes, args.benchmark
            )
        if args.command != "analyze":
            if args.database is None:
                raise ValueError("database_required")
            store = Memory(args.database)
        if args.command == "ingest":
            if request.item is None:
                raise ValueError("memory_item_required")
            store.ingest(registry, request, request.item, time.time())
            output = {"status": "ingested", "memory_id": request.item.memory_id}
        elif args.command == "retrieve":
            output = {
                "items": [
                    item.model_dump() for item in store.retrieve(registry, request, time.time())
                ]
            }
        elif args.command == "audit":
            output = {"events": store.audit(registry, request, time.time(), args.after)}
        elif args.command == "export":
            output = store.export(registry, request, time.time()).model_dump(mode="json")
        else:
            decision = (
                analyze(registry, request, evidence, args.registry_sha256)
                if args.command == "analyze"
                else runOnce(store, registry, request, evidence, args.registry_sha256)
            )
            output = decision.model_dump(mode="json")
        print(json.dumps(output, allow_nan=False, indent=2))
        return 2 if output.get("consensus", {}).get("posture") == "abstain" else 0
    except (ValueError, OSError, TypeError, KeyError, sqlite3.Error):
        print(
            json.dumps(
                {
                    "status": "rejected",
                    "reason": "runtime_validation_or_permission_failed",
                    "execution": "not_applied",
                    "safety_authorized": False,
                }
            ),
            file=sys.stderr,
        )
        return 1
    finally:
        if store:
            store.close()


if __name__ == "__main__":
    sys.exit(main())

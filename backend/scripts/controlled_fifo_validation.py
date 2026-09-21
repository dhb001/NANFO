"""Prepare/acquire/replay EMULATION-only controlled FIFO; never installs receiver trust."""

import argparse
import json
from pathlib import Path

from pydantic import ValidationError

from app.modules.autonomy.artifact_io import ArtifactRef, ArtifactStore, EvidenceError
from app.modules.simulation.controlled_fifo_campaign import acquire, prepare
from app.modules.simulation.controlled_fifo_verification import blocked_receiver_result, blocked_rf_result, evaluate
from app.modules.simulation.qualification_acquisition import write_new


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "acquire", "evaluate", "rf-blocked", "receiver-blocked"])
    parser.add_argument("--source-root")
    parser.add_argument("--protocol-root")
    parser.add_argument("--capture-root")
    parser.add_argument("--path")
    parser.add_argument("--sha256")
    parser.add_argument("--size", type=int)
    parser.add_argument("--registered-at-unix-ns", type=int)
    parser.add_argument("--registered-protocol-sha256")
    parser.add_argument("--network-id")
    parser.add_argument("--run-id")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            result = prepare(args.output, network_id=args.network_id, run_id=args.run_id)
        elif args.command == "rf-blocked":
            result = blocked_rf_result()
            write_new(args.output, result)
        elif args.command == "receiver-blocked":
            result = blocked_receiver_result(ArtifactStore(args.source_root))
            write_new(args.output, result)
        else:
            ref = ArtifactRef(path=args.path, sha256=args.sha256, size_bytes=args.size)
            store = ArtifactStore(args.protocol_root)
            if args.command == "acquire":
                if args.registered_at_unix_ns is None:
                    parser.error("external preregistration receipt time required")
                result = acquire(store, ref, registered_at_unix_ns=args.registered_at_unix_ns, output=args.output)
            else:
                result = evaluate(store, ArtifactStore(args.capture_root), ref,
                                  registered_protocol_sha256=args.registered_protocol_sha256,
                                  registered_at_unix_ns=args.registered_at_unix_ns)
                write_new(args.output, result)
        print(json.dumps(result, sort_keys=True))
        return 2 if args.command in ("rf-blocked", "receiver-blocked") else 0
    except (EvidenceError, ValidationError, OSError, TypeError, KeyError, ValueError) as exc:
        print(json.dumps({"status": "blocked", "physical_qualified": False,
                          "reason": str(exc) if isinstance(exc, EvidenceError) else "invalid_or_incomplete_campaign"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

"""Operator-only loopback acquisition; no privileged emulation or physical claim."""

import argparse
import json
from pathlib import Path

from pydantic import ValidationError

from app.modules.autonomy.artifact_io import ArtifactRef, ArtifactStore, EvidenceError, parse_json
from app.modules.simulation.qualification_acquisition import acquire_local, collector_digest, prepare_local, verify_native_events
from app.modules.simulation.qualification_protocol import RawCapture


def inspect_local(root: str) -> dict:
    """Replay acquired bytes before attestation; never elevate to trusted campaign."""
    store = ArtifactStore(root)
    complete = store.document("acquisition-complete.json")
    rows = []
    for ref in complete["captures"]:
        capture = RawCapture.model_validate(parse_json(store.referenced(ArtifactRef(**ref))))
        events = {}
        for source in capture.native_sources:
            native = parse_json(store.referenced(source))
            if native.get("schema_version") == "nanfo.loopback-events.v1":
                events[native["start_unix_seconds"]] = native
        for record in capture.records:
            native = events.pop(record.observed_at_unix_seconds, None)
            if native is None:
                raise EvidenceError("native_acquisition_window_missing")
            verify_native_events(native, record.measurement)
            q = record.measurement["queues"][0]
            rows.append(dict(sample_id=record.sample_id, arrived_bytes=q["arrivals"]["after"],
                             served_bytes=q["departures"]["after"], queue_after_bytes=q["queue_after_bytes"],
                             complete=record.measurement["measurement_complete"]))
        if events:
            raise EvidenceError("unmatched_native_acquisition_windows")
    return {"raw_event_replay_passed": True, "rows": rows, "trusted": False,
            "physical_qualified": False, "missing": ["operator measurement attestation", "accepted bound guarantee", "trusted installation"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collector-sha256", action="store_true")
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--inspect-local", action="store_true")
    parser.add_argument("--network-id")
    parser.add_argument("--run-id")
    parser.add_argument("--root")
    parser.add_argument("--protocol")
    parser.add_argument("--protocol-sha256")
    parser.add_argument("--protocol-size", type=int)
    parser.add_argument("--registered-at", type=float)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.collector_sha256:
        print(collector_digest())
        return 0
    if args.inspect_local:
        if not args.root:
            parser.error("inspect-local requires root")
        try:
            print(json.dumps(inspect_local(args.root), sort_keys=True))
            return 0
        except (EvidenceError, ValidationError, KeyError, TypeError):
            print(json.dumps({"reason": "local_acquisition_replay_failed", "trusted": False}))
            return 2
    if args.prepare:
        if not all((args.output, args.network_id, args.run_id)):
            parser.error("prepare requires new output directory, network-id and run-id")
        try:
            print(json.dumps(prepare_local(args.output, network_id=args.network_id, run_id=args.run_id), sort_keys=True))
            return 0
        except (EvidenceError, ValidationError, OSError):
            print(json.dumps({"reason": "preregistration_preparation_failed"}))
            return 2
    if not all((args.root, args.protocol, args.protocol_sha256, args.protocol_size, args.registered_at, args.output)):
        parser.error("supply preregistered protocol reference, receipt time and new output directory")
    try:
        captures = acquire_local(ArtifactStore(args.root), ArtifactRef(
            path=args.protocol, sha256=args.protocol_sha256, size_bytes=args.protocol_size,
        ), output=args.output, registered_at=args.registered_at,
            expected_protocol_sha256=args.protocol_sha256)
        result = {"captures": [r.model_dump() for r in captures], "physical_qualified": False}
    except (EvidenceError, ValidationError, OSError) as exc:
        print(json.dumps({"reason": str(exc) if isinstance(exc, EvidenceError) else "acquisition_failed_partial_evidence_retained"}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

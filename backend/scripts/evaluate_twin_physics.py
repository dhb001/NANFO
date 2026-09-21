"""Offline ADR-021 operator toolkit. Run from backend with PYTHONPATH=.

python scripts/evaluate_twin_physics.py rf --input rf.json --output-dir /tmp/results
Use MODE --schema to print the strict request JSON Schema.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
from pathlib import Path

from pydantic import ValidationError

from app.modules.simulation import evaluator
from app.modules.simulation.calibration import CalibrationRequest, evaluate_calibration
from app.modules.simulation.rf import RFRequest, evaluate_rf
from app.modules.simulation.snapshot import SnapshotRequest, build_snapshot
from app.modules.simulation.spatial_rf import SpatialRFRequest, build_spatial_rf

MAX_INPUT_BYTES = 2 * 1024 * 1024
MAX_OUTPUT_BYTES = 16 * 1024 * 1024
REQUESTS = {
    "rf": RFRequest,
    "calibration": CalibrationRequest,
    "snapshot": SnapshotRequest,
    "spatial-rf": SpatialRFRequest,
}


def _directory_fd(path: Path) -> int:
    """Pin an existing directory; reject symlinks in every component (Linux)."""
    absolute = path.absolute()
    fd = os.open(absolute.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for component in absolute.parts[1:]:
            if component == "..":
                raise ValueError("Parent traversal is not allowed")
            child = os.open(
                component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd
            )
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate JSON object key")
        value[key] = item
    return value


def _invalid_constant(value: str) -> None:
    raise ValueError("Nonfinite JSON number")


def read_request(path: Path, mode: str):
    directory = _directory_fd(path.parent)
    try:
        fd = os.open(
            path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
        )
    finally:
        os.close(directory)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_INPUT_BYTES:
            raise ValueError("Input must be a regular JSON file at most 2 MiB")
        data = stream.read(MAX_INPUT_BYTES + 1)
    if len(data) > MAX_INPUT_BYTES:
        raise ValueError("Input exceeds 2 MiB")
    value = json.loads(
        data, object_pairs_hook=_unique_object, parse_constant=_invalid_constant
    )
    return REQUESTS[mode].model_validate(value)


def write_result(directory: Path, name: str, result: dict) -> None:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}\.json", name):
        raise ValueError("Output name must be a simple .json filename")
    data = (
        json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n"
    ).encode()
    if len(data) > MAX_OUTPUT_BYTES:
        raise ValueError("Output exceeds 16 MiB")
    fd = _directory_fd(directory)
    try:
        output = os.open(
            name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd
        )
        try:
            with os.fdopen(output, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        except BaseException:
            os.unlink(name, dir_fd=fd)
            raise
    finally:
        os.close(fd)


def evaluate(mode: str, request) -> dict:
    if mode == "spatial-rf":
        rf_request, provenance = build_spatial_rf(request)
        return {
            "rf_request": rf_request.model_dump(mode="json"),
            "provenance": provenance.model_dump(mode="json"),
            "evaluation": evaluate_rf(rf_request).model_dump(mode="json"),
        }
    if mode == "rf":
        return evaluate_rf(request).model_dump(mode="json")
    if mode == "calibration":
        return evaluate_calibration(request).model_dump(mode="json")
    config, provenance = build_snapshot(request)
    checkpoint = evaluator.initial_checkpoint(config)
    while checkpoint["state"]["tick"] < config.duration_ticks:
        checkpoint = evaluator.advance(config, checkpoint, ticks=32)
    return {
        "scenario_config": config.model_dump(mode="json"),
        "provenance": provenance.model_dump(mode="json"),
        "evaluation": evaluator.output(config, checkpoint),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=REQUESTS)
    parser.add_argument("--schema", action="store_true")
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--output-name", default="result.json")
    args = parser.parse_args(argv)
    if args.schema:
        print(
            json.dumps(
                REQUESTS[args.mode].model_json_schema(), sort_keys=True, indent=2
            )
        )
        return 0
    if args.input is None or args.output_dir is None:
        parser.error("--input and --output-dir are required without --schema")
    try:
        request = read_request(args.input, args.mode)
        result = evaluate(args.mode, request)
        write_result(args.output_dir, args.output_name, result)
    except ValidationError:
        print(
            "Invalid request: strict schema, bounds or consistency check failed; use --schema",
            file=sys.stderr,
        )
        return 2
    except (OSError, ValueError, RecursionError):
        print(
            "Evaluation failed: invalid JSON, unsafe/unavailable path or resource bound",
            file=sys.stderr,
        )
        return 2
    print(f"Wrote {args.output_name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

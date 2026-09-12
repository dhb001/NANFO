"""Read-only ADR-013 operator assessment. No database, lab or model imports."""

import argparse
import json
from pathlib import Path

from pydantic import ValidationError

from app.modules.autonomy.artifact_io import ArtifactStore, EvidenceError
from app.modules.autonomy.calibration import (
    CalibrationInput,
    CalibrationPlan,
    MeasuredTraces,
    assess_calibration,
    universal_queue_bound,
)
from app.modules.autonomy.qualification import (
    EvaluationPlan,
    MeasuredEpisode,
    ProducerQualification,
    QualificationDossier,
    assessment_error,
    import_qualification,
)


def assess(*, qualification=None, calibration=None):
    results = {}
    try:
        store = ArtifactStore.from_environment()
    except EvidenceError as exc:
        store = None
        results["operator_config"] = assessment_error(exc, "operator_config")
    for name, path, validate in (
        ("qualification", qualification, import_qualification),
        ("calibration", calibration, assess_calibration),
    ):
        if path is None:
            results[name] = {
                "qualified": False,
                "reasons": [f"{name}_artifact_not_supplied"],
            }
        elif store is None:
            results[name] = {
                "qualified": False,
                "reasons": ["operator_artifact_root_unconfigured"],
            }
        else:
            try:
                results[name] = validate(store, path)
            except (EvidenceError, ValidationError, OverflowError) as exc:
                results[name] = assessment_error(exc, name)
    reasons = list(
        dict.fromkeys(
            reason
            for result in results.values()
            for reason in result.get("reasons", [])
        )
    )
    reasons.extend(
        [
            "observation_contract_incompatible",
            "passive_observation_provider_unavailable",
            "experiment_ownership_not_runtime_authority",
            "frozen_inference_not_installed",
            "runtime_control_incompatible",
            "autonomous_executor_unavailable",
            "autonomous_recovery_unavailable",
            "operator_recovery_required",
        ]
    )
    qspec = results["qualification"].get("spec_sha256")
    cspec = results["calibration"].get("spec_sha256")
    if (
        qspec
        and cspec
        and (
            qspec != cspec
            or results["qualification"].get("contract_sha256")
            != results["calibration"].get("contract_sha256")
        )
    ):
        reasons.append("qualification_calibration_contract_mismatch")
    return {
        "schema_version": "nanfo.autonomy-readiness.v1",
        "ready": False,
        "online_learning": False,
        "production_dispatch": False,
        "automatic_step": False,
        "read_only": True,
        "reasons": reasons,
        "assessments": results,
        "runtime": {
            "required_action": "linux-frr-host-route",
            "manual_action": "ovs-openflow",
            "executor_installed": False,
            "recovery_installed": False,
        },
        "next_steps": [
            "Supply immutable operator-pinned measured qualification evidence, not best.json.",
            "Collect predeclared train-only endpoint queue/counter calibration traces; do not relabel peaks as endpoints.",
            "Establish causal arrival/service/error guarantees including transition and service outage.",
            "Obtain a fresh complete passive observation contract and distinct owned runtime authority.",
            "Do not call experiment step or synthesize ADR-010 manual approval.",
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--qualification", help="Relative artifact path under operator-configured root"
    )
    parser.add_argument(
        "--calibration",
        help="Relative calibration-input path; diagnostics are recomputed",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Create a new assessment JSON outside the input root; never overwrite",
    )
    schemas = {
        "qualification": QualificationDossier,
        "producer": ProducerQualification,
        "evaluation-plan": EvaluationPlan,
        "episode": MeasuredEpisode,
    }
    parser.add_argument(
        "--schema", choices=schemas, help="Print the exact offline JSON schema and exit"
    )
    args = parser.parse_args(argv)
    if args.schema:
        print(json.dumps(schemas[args.schema].model_json_schema(), sort_keys=True))
        return 0
    result = assess(qualification=args.qualification, calibration=args.calibration)
    if args.output:
        import os

        root = os.environ.get("NANFO_AUTONOMY_ARTIFACT_ROOT")
        destination = args.output.resolve()
        if root and destination.is_relative_to(Path(root).resolve()):
            parser.error("output must be outside the read-only artifact root")
        try:
            with destination.open("x", encoding="utf-8") as output:
                json.dump(result, output, sort_keys=True, allow_nan=False, indent=2)
                output.write("\n")
        except OSError:
            parser.error("output must be a new writable file with an existing parent")
    print(json.dumps(result, allow_nan=False, sort_keys=True))
    return 0 if result["ready"] else 2


def calibration_main(argv=None):
    parser = argparse.ArgumentParser(
        description="Train-only/holdout diagnostics; never installs safety bounds"
    )
    parser.add_argument("--calibration", help="Relative calibration-input path")
    parser.add_argument("--universal-arrival-mbps", type=float)
    parser.add_argument("--queue-bytes", type=float, default=0.0)
    parser.add_argument("--dt-seconds", type=float, default=2.0)
    parser.add_argument("--error-bytes", type=float, default=0.0)
    schemas = {
        "input": CalibrationInput,
        "plan": CalibrationPlan,
        "traces": MeasuredTraces,
    }
    parser.add_argument("--schema", choices=schemas)
    args = parser.parse_args(argv)
    if args.schema:
        print(json.dumps(schemas[args.schema].model_json_schema(), sort_keys=True))
        return 0
    if (args.calibration is None) == (args.universal_arrival_mbps is None):
        parser.error("supply exactly one of --calibration or --universal-arrival-mbps")
    try:
        if args.calibration:
            result = assess_calibration(
                ArtifactStore.from_environment(), args.calibration
            )
        else:
            result = {
                "qualified": False,
                "conditional_universal_diagnostic": universal_queue_bound(
                    queue_bytes=args.queue_bytes,
                    arrival_upper_bytes_per_second=args.universal_arrival_mbps
                    * 1e6
                    / 8,
                    dt_seconds=args.dt_seconds,
                    error_upper_bytes=args.error_bytes,
                ),
                "reasons": [
                    "arrival_cap_requires_physical_justification",
                    "trusted_calibration_not_installed",
                ],
            }
    except (EvidenceError, ValidationError, OverflowError) as exc:
        result = assessment_error(exc, "calibration")
    print(json.dumps(result, allow_nan=False, sort_keys=True))
    return 2

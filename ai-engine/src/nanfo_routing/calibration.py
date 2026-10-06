"""C17 confidence calibration tooling: temperature scaling, ECE and a reliability report.

`calibrate()` returns a content-addressed artifact. It is `calibrated` (and carries a
`calibration_id`) only for measured held-out evidence of a pinned model that meets the declared
ECE bound; synthetic or insufficient data always yields calibrated=false and no id, so the
tooling cannot fabricate a calibration. No calibration exists for any historical model:
autonomous dispatch stays gated by C17 until a genuine artifact is produced from fresh measured
evidence and installed by the backend.
"""

import hashlib
import json
import math
import re

from .contracts import jsonBytes

SCHEMA = "nanfo.confidence-calibration/v1"
METHOD = "temperature_scaled_policy_probability"
MEASURED = "measured-held-out"
DATASET_KINDS = (MEASURED, "synthetic-unit-fixture")
DEFAULT_BINS = 15
MAX_ECE = 0.05
MIN_SAMPLES = 500
TEMPERATURE_BOUNDS = (0.05, 20.0)
SHA256 = re.compile(r"[a-f0-9]{64}")
LIMITATIONS = [
    "Confidence is the temperature-scaled probability that the chosen route is the better "
    "route under the declared label rule, on the declared dataset only.",
    "Calibration does not qualify a model, prove safety or authorize autonomous dispatch.",
]


def _probabilities(row, temperature):
    scaled = [value / temperature for value in row]
    top = max(scaled)
    weights = [math.exp(value - top) for value in scaled]
    total = math.fsum(weights)
    return [weight / total for weight in weights]


def _samples(logits, labels):
    if not logits or len(logits) != len(labels):
        raise ValueError("calibration logits and labels must be non-empty and paired")
    width = len(logits[0])
    for row, label in zip(logits, labels, strict=True):
        if (
            len(row) != width
            or width < 2
            or any(type(value) not in (int, float) or not math.isfinite(value) for value in row)
            or type(label) is not int
            or not 0 <= label < width
        ):
            raise ValueError("invalid calibration sample")


def negativeLogLikelihood(logits, labels, temperature):
    total = math.fsum(
        -math.log(max(_probabilities(row, temperature)[label], 1e-300))
        for row, label in zip(logits, labels, strict=True)
    )
    return total / len(labels)


def fitTemperature(logits, labels):
    """Minimize NLL; it is convex in the inverse temperature, so golden-section search is exact."""
    _samples(logits, labels)
    low, high = 1 / TEMPERATURE_BOUNDS[1], 1 / TEMPERATURE_BOUNDS[0]
    ratio = (math.sqrt(5) - 1) / 2

    def loss(beta):
        return negativeLogLikelihood(logits, labels, 1 / beta)

    left, right = high - ratio * (high - low), low + ratio * (high - low)
    leftLoss, rightLoss = loss(left), loss(right)
    for _ in range(80):
        if leftLoss <= rightLoss:
            high, right, rightLoss = right, left, leftLoss
            left = high - ratio * (high - low)
            leftLoss = loss(left)
        else:
            low, left, leftLoss = left, right, rightLoss
            right = low + ratio * (high - low)
            rightLoss = loss(right)
    return 1 / ((low + high) / 2)


def reliability(confidences, correct, bins=DEFAULT_BINS):
    """Equal-width reliability bins and the count-weighted expected calibration error."""
    if not 1 <= bins <= 100 or len(confidences) != len(correct) or not confidences:
        raise ValueError("invalid reliability request")
    rows, error = [], 0.0
    for index in range(bins):
        lower, upper = index / bins, (index + 1) / bins
        members = [
            position
            for position, value in enumerate(confidences)
            if lower < value <= upper or (index == 0 and value == 0)
        ]
        row = {"lower": lower, "upper": upper, "count": len(members)}
        if members:
            confidence = math.fsum(confidences[i] for i in members) / len(members)
            accuracy = sum(correct[i] for i in members) / len(members)
            row.update(mean_confidence=confidence, accuracy=accuracy)
            error += len(members) / len(confidences) * abs(accuracy - confidence)
        rows.append(row)
    return rows, error


def _summary(logits, labels, temperature, bins):
    probabilities = [_probabilities(row, temperature) for row in logits]
    confidences = [max(row) for row in probabilities]
    correct = [
        row.index(max(row)) == label for row, label in zip(probabilities, labels, strict=True)
    ]
    rows, error = reliability(confidences, correct, bins)
    brier = math.fsum(
        math.fsum((p - (index == label)) ** 2 for index, p in enumerate(row))
        for row, label in zip(probabilities, labels, strict=True)
    ) / len(labels)
    return {
        "ece": error,
        "nll": negativeLogLikelihood(logits, labels, temperature),
        "brier": brier,
        "accuracy": sum(correct) / len(correct),
        "reliability": rows,
    }


def _identity(model, dataset):
    if (
        type(model) is not dict
        or set(model) != {"checkpoint_sha256", "weights_sha256"}
        or not all(type(v) is str and SHA256.fullmatch(v) for v in model.values())
    ):
        raise ValueError("calibration requires the pinned checkpoint and weights SHA-256")
    if (
        type(dataset) is not dict
        or set(dataset) != {"kind", "split", "evidence_sha256", "label_rule"}
        or dataset["kind"] not in DATASET_KINDS
        or dataset["split"] not in ("validation", "calibration")
        or type(dataset["evidence_sha256"]) is not str
        or not SHA256.fullmatch(dataset["evidence_sha256"])
        or type(dataset["label_rule"]) is not str
        or not 1 <= len(dataset["label_rule"]) <= 500
    ):
        raise ValueError("invalid calibration dataset declaration")


def _digest(artifact):
    body = {k: v for k, v in artifact.items() if k not in ("calibration_id", "report_sha256")}
    return hashlib.sha256(jsonBytes(body)).hexdigest()


def calibrate(
    logits, labels, *, model, dataset, bins=DEFAULT_BINS, maxEce=MAX_ECE, minSamples=MIN_SAMPLES
):
    _samples(logits, labels)
    _identity(model, dataset)
    temperature = fitTemperature(logits, labels)
    before, after = _summary(logits, labels, 1.0, bins), _summary(logits, labels, temperature, bins)
    calibrated = (
        dataset["kind"] == MEASURED and len(labels) >= minSamples and after["ece"] <= maxEce
    )
    artifact = {
        "schema": SCHEMA,
        "method": METHOD,
        "model": dict(model),
        "dataset": dict(dataset),
        "samples": len(labels),
        "actions": len(logits[0]),
        "temperature": temperature,
        "bins": bins,
        "before": before,
        "after": after,
        "acceptance": {
            "max_ece": maxEce,
            "min_samples": minSamples,
            "required_dataset_kind": MEASURED,
        },
        "calibrated": calibrated,
        "limitations": list(LIMITATIONS),
    }
    digest = _digest(artifact)
    artifact["report_sha256"] = digest
    artifact["calibration_id"] = f"{SCHEMA}:{digest}" if calibrated else None
    return artifact


def validateCalibration(artifact):
    """Re-derive every claim; a calibration_id exists exactly for a passing measured artifact."""
    if type(artifact) is not dict or artifact.get("schema") != SCHEMA:
        raise ValueError("not a calibration artifact")
    _identity(artifact["model"], artifact["dataset"])
    digest = _digest(artifact)
    acceptance, after = artifact["acceptance"], artifact["after"]
    passed = (
        artifact["dataset"]["kind"] == MEASURED
        and artifact["samples"] >= acceptance["min_samples"]
        and after["ece"] <= acceptance["max_ece"]
        and acceptance["required_dataset_kind"] == MEASURED
    )
    if (
        artifact.get("report_sha256") != digest
        or artifact.get("method") != METHOD
        or not TEMPERATURE_BOUNDS[0] <= artifact["temperature"] <= TEMPERATURE_BOUNDS[1]
        or artifact.get("calibrated") is not passed
        or artifact.get("calibration_id") != (f"{SCHEMA}:{digest}" if passed else None)
    ):
        raise ValueError("calibration artifact claims differ from its evidence")
    return artifact


def calibratedConfidence(artifact, logits):
    """The C17 confidence of one decision: value, method, calibrated and calibration_id."""
    validateCalibration(artifact)
    _samples([logits], [0])
    if len(logits) != artifact["actions"]:
        raise ValueError("decision action count differs from the calibration")
    return {
        "value": max(_probabilities(logits, artifact["temperature"])),
        "method": METHOD,
        "calibrated": artifact["calibrated"],
        "calibration_id": artifact["calibration_id"],
    }


def _readJson(path, limit=64 * 1024 * 1024):
    with path.open("rb") as source:
        raw = source.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("calibration input exceeds bound")

    def refuse(value):
        raise ValueError("non-finite JSON number")

    return json.loads(raw, parse_constant=refuse)


def main(argv=None):
    """`calibrate SAMPLES OUTPUT` ({logits, labels, model, dataset}) or `validate ARTIFACT`."""
    import argparse
    import sys
    from pathlib import Path

    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("calibrate")
    run.add_argument("samples", type=Path)
    run.add_argument("output", type=Path)
    check = commands.add_parser("validate")
    check.add_argument("artifact", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            result = validateCalibration(_readJson(args.artifact))
        else:
            value = _readJson(args.samples)
            result = calibrate(
                value["logits"], value["labels"], model=value["model"], dataset=value["dataset"]
            )
            with args.output.open("xb") as output:
                output.write(jsonBytes(result))
        print(
            json.dumps(
                {
                    "calibrated": result["calibrated"],
                    "calibration_id": result["calibration_id"],
                    "ece": result["after"]["ece"],
                }
            )
        )
        return 0
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)[:512]}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

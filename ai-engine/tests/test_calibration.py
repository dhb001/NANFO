"""C17 calibration tooling on synthetic data only; never a calibration of a real model."""

import json
import math
import random
import re

import pytest

from nanfo_routing import calibration as c

MODEL = {"checkpoint_sha256": "a" * 64, "weights_sha256": "b" * 64}
SYNTHETIC = {
    "kind": "synthetic-unit-fixture",
    "split": "validation",
    "evidence_sha256": "c" * 64,
    "label_rule": "synthetic: label drawn from the true fixture probability",
}
MEASURED = {**SYNTHETIC, "kind": c.MEASURED, "label_rule": "better measured route (fixture)"}


def overconfident(count, seed=11, scale=4.0):
    """True P(action 0) = sigmoid(z); the reported logits are `scale` times too sharp."""
    rng = random.Random(seed)
    logits, labels = [], []
    for _ in range(count):
        z = rng.uniform(-2.5, 2.5)
        truth = 1 / (1 + math.exp(-z))
        logits.append([scale * z / 2, -scale * z / 2])
        labels.append(0 if rng.random() < truth else 1)
    return logits, labels


def test_temperature_scaling_reduces_ece_and_keeps_decisions():
    logits, labels = overconfident(4000)
    artifact = c.calibrate(logits, labels, model=MODEL, dataset=MEASURED)
    assert artifact["temperature"] == pytest.approx(4.0, rel=0.15)
    assert artifact["after"]["ece"] < 0.03 < artifact["before"]["ece"]
    assert artifact["after"]["nll"] < artifact["before"]["nll"]
    assert artifact["after"]["accuracy"] == artifact["before"]["accuracy"]
    for summary in (artifact["before"], artifact["after"]):
        assert len(summary["reliability"]) == c.DEFAULT_BINS
        assert sum(row["count"] for row in summary["reliability"]) == 4000
    assert artifact["calibrated"] and c.validateCalibration(artifact) is artifact
    assert artifact["calibration_id"] == c.SCHEMA + ":" + artifact["report_sha256"]


def test_synthetic_or_small_or_poor_data_never_yields_a_calibration():
    logits, labels = overconfident(4000)
    synthetic = c.calibrate(logits, labels, model=MODEL, dataset=SYNTHETIC)
    assert synthetic["after"]["ece"] <= c.MAX_ECE
    assert not synthetic["calibrated"] and synthetic["calibration_id"] is None
    small = c.calibrate(logits[:200], labels[:200], model=MODEL, dataset=MEASURED)
    assert not small["calibrated"] and small["calibration_id"] is None
    wrong = [1 - label for label in labels]  # confident and mostly wrong: T cannot fix it
    poor = c.calibrate(logits, wrong, model=MODEL, dataset=MEASURED)
    assert poor["after"]["ece"] > c.MAX_ECE and not poor["calibrated"]
    for artifact in (synthetic, small, poor):
        assert c.validateCalibration(artifact) is artifact


@pytest.mark.parametrize(
    "mutate",
    [
        lambda a: a.update(temperature=a["temperature"] * 1.01),
        lambda a: a.update(calibrated=False),
        lambda a: a.update(calibration_id=None),
        lambda a: a["dataset"].update(kind="synthetic-unit-fixture"),
        lambda a: a["after"].update(ece=0.2),
        lambda a: a.update(method="policy_action_probability"),
    ],
)
def test_tampered_or_self_asserted_artifacts_are_refused(mutate):
    logits, labels = overconfident(1000)
    artifact = c.calibrate(logits, labels, model=MODEL, dataset=MEASURED)
    mutate(artifact)
    with pytest.raises(ValueError):
        c.validateCalibration(artifact)


def test_inputs_and_declarations_fail_closed():
    logits, labels = overconfident(10)
    for bad in (
        ([], []),
        (logits, labels[:-1]),
        ([[0.0, math.nan]] + logits[1:], labels),
        ([[0.0]] * 10, [0] * 10),
        (logits, [2] + labels[1:]),
        (logits, [True] + labels[1:]),
    ):
        with pytest.raises(ValueError):
            c.calibrate(*bad, model=MODEL, dataset=MEASURED)
    for model, dataset in (
        ({"checkpoint_sha256": "a" * 64}, MEASURED),
        (MODEL, {**MEASURED, "kind": "self-asserted"}),
        (MODEL, {**MEASURED, "split": "test"}),
        (MODEL, {**MEASURED, "evidence_sha256": "x"}),
    ):
        with pytest.raises(ValueError):
            c.calibrate(logits, labels, model=model, dataset=dataset)


def test_confidence_matches_the_backend_c17_contract():
    logits, labels = overconfident(2000)
    artifact = c.calibrate(logits, labels, model=MODEL, dataset=MEASURED)
    confidence = c.calibratedConfidence(artifact, [3.0, -1.0])
    assert set(confidence) == {"value", "method", "calibrated", "calibration_id"}
    assert 0.5 < confidence["value"] < 1 and confidence["calibrated"] is True
    # backend app.modules.autonomy.schemas.Confidence: pattern, id length, honest method.
    assert re.fullmatch(r"[a-z][a-z0-9_.:/-]{0,127}", confidence["method"])
    assert confidence["method"] != "policy_action_probability"
    assert 1 <= len(confidence["calibration_id"]) <= 200
    uncalibrated = c.calibrate(logits, labels, model=MODEL, dataset=SYNTHETIC)
    assert c.calibratedConfidence(uncalibrated, [3.0, -1.0])["calibration_id"] is None
    with pytest.raises(ValueError, match="action count"):
        c.calibratedConfidence(artifact, [1.0, 0.0, -1.0])
    assert c.fitTemperature(*overconfident(500, scale=1.0)) == pytest.approx(1.0, rel=0.3)


def test_cli_writes_exclusively_and_validates(tmp_path, capsys):
    logits, labels = overconfident(5000)
    samples = tmp_path / "samples.json"
    value = dict(logits=logits, labels=labels, model=MODEL, dataset=SYNTHETIC)
    samples.write_text(json.dumps(value))
    output = tmp_path / "calibration.json"
    assert c.main(["calibrate", str(samples), str(output)]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "calibrated": False,
        "calibration_id": None,
        "ece": json.loads(output.read_bytes())["after"]["ece"],
    }
    assert c.main(["validate", str(output)]) == 0
    capsys.readouterr()
    assert c.main(["calibrate", str(samples), str(output)]) == 1  # never overwrites
    samples.write_text('{"logits": [[NaN, 0]], "labels": [0]}')
    assert c.main(["calibrate", str(samples), str(tmp_path / "other.json")]) == 1
    assert "non-finite" in capsys.readouterr().err

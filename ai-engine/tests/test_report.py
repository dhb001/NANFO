"""Offline evidence reconstruction tests, never a measured training campaign."""

import hashlib
import json

import pytest

from nanfo_routing import cli
from nanfo_routing.contracts import jsonBytes


def session(tmp_path, monkeypatch, transport, name, seed=2001, mode="matched"):
    monkeypatch.setattr(cli, "DockerTransport", lambda *args: transport)
    output = tmp_path / name
    assert (
        cli.main(
            [
                "evaluate",
                "--operator-experiment",
                "--policy",
                "heuristic" if mode == "matched" else "ospf",
                "--mode",
                mode,
                "--split",
                "validation",
                "--seed",
                str(seed),
                "--episodes",
                "2",
                "--steps",
                "4",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    return output / "summary.json"


def test_report_reconstructs_metrics_from_raw_measurements(tmp_path, monkeypatch, transport):
    path = session(tmp_path, monkeypatch, transport, "offline-a")
    second = session(tmp_path, monkeypatch, transport, "offline-b")
    result = cli.report([path, second])
    assert result["matched_offered_schedules"] and result["comparable_held_out_schedules"]
    row = result["sessions"][0]
    assert len(row["reconstructed_phases"]) == 10
    assert row["derived_metrics"]["valid_decisions"] == 8
    assert row["measured_rates"][0]["actual_offered_mbps"][0] > 0
    assert any(
        "V4 delivered totals include verified queue drain" in text for text in row["limitations"]
    )
    stored = json.loads(path.read_bytes())
    assert not any("receiver cutoff" in text for text in stored["limitations"])
    assert "measurement_semantics" not in result


def test_ospf_matched_schedule_is_comparable_dataplane(tmp_path, monkeypatch, transport):
    sdn = session(tmp_path, monkeypatch, transport, "offline-sdn")
    ospf = session(tmp_path, monkeypatch, transport, "offline-ospf", mode="ospf")
    result = cli.report([sdn, ospf])
    assert result["matched_offered_schedules"]
    assert result["comparable_held_out_schedules"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("seeds", [2002]),
        ("window_seconds", 2.0),
        ("valid_transitions", 999),
        ("environment_spec", {}),
    ],
)
def test_report_rejects_summary_labels_not_matching_trace(
    tmp_path, monkeypatch, transport, field, value
):
    path = session(tmp_path, monkeypatch, transport, "offline-a")
    summary = json.loads(path.read_bytes())
    summary[field] = value
    path.write_bytes(jsonBytes(summary))
    with pytest.raises(ValueError):
        cli.report([path])


def test_report_rejects_forged_reward_even_with_updated_digest(tmp_path, monkeypatch, transport):
    path = session(tmp_path, monkeypatch, transport, "offline-a")
    evidence = path.parent / "evidence.jsonl"
    rows = [json.loads(line) for line in evidence.read_bytes().splitlines()]
    next(row for row in rows if row["kind"] == "decision")["reward"]["total"] = 999.0
    encoded = b"".join(jsonBytes(row) + b"\n" for row in rows)
    evidence.write_bytes(encoded)
    summary = json.loads(path.read_bytes())
    summary["evidence_sha256"] = hashlib.sha256(encoded).hexdigest()
    path.write_bytes(jsonBytes(summary))
    with pytest.raises(ValueError, match="reward"):
        cli.report([path])


def test_report_replays_checkpoint_not_logged_policy_label(tmp_path, monkeypatch, transport):
    from nanfo_routing.artifacts import saveCheckpoint
    from nanfo_routing.ppo import PPO

    path = session(tmp_path, monkeypatch, transport, "replay")
    bundle = tmp_path / "fixture.ptz"
    agent = PPO()
    manifest = saveCheckpoint(
        bundle,
        agent,
        provenance="offline-fixture-not-trained-model",
        trainingSeeds=[],
        episodes=0,
        evidenceHash="0" * 64,
    )
    summary = json.loads(path.read_bytes())
    summary["policy"] = "ppo"
    evidence = path.parent / "evidence.jsonl"
    rows = [json.loads(line) for line in evidence.read_bytes().splitlines()]
    rows[0]["summary"]["policy"] = "ppo"
    for row in rows:
        if row["kind"] == "decision":
            row["probabilities"] = [1.0, 0.0]
    encoded = b"".join(jsonBytes(row) + b"\n" for row in rows)
    evidence.write_bytes(encoded)
    summary["evidence_sha256"] = hashlib.sha256(encoded).hexdigest()
    path.write_bytes(jsonBytes(summary))
    monkeypatch.setattr(cli, "loadCheckpoint", lambda path: (agent, manifest))
    with pytest.raises(ValueError, match="reproduce measured decisions"):
        cli.report([path], checkpoint=bundle)


def test_report_rejects_coherent_seed_relabel_with_rehashed_trace(tmp_path, monkeypatch, transport):
    path = session(tmp_path, monkeypatch, transport, "seed-relabel", seed=2600)
    evidence = path.parent / "evidence.jsonl"
    summary = json.loads(path.read_bytes())
    rows = [json.loads(line) for line in evidence.read_bytes().splitlines()]

    def relabel(value):
        if isinstance(value, dict):
            return {key: relabel(item) for key, item in value.items()}
        if isinstance(value, list):
            return [relabel(item) for item in value]
        return {2600: 2998, 2601: 2999}.get(value, value) if type(value) is int else value

    # Every request, response, session label, episode and digest agrees after relabeling.
    encoded = b"".join(jsonBytes(relabel(row)) + b"\n" for row in rows)
    evidence.write_bytes(encoded)
    summary = relabel(summary)
    summary["evidence_sha256"] = hashlib.sha256(encoded).hexdigest()
    summary["evidence_bytes"] = len(encoded)
    path.write_bytes(jsonBytes(summary))
    with pytest.raises(ValueError, match="reconstructed seeded stationary"):
        cli.report([path])

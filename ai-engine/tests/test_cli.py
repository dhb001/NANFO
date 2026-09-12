import hashlib
import json
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

from nanfo_routing import cli
from nanfo_routing.artifacts import saveCheckpoint, trainingDistribution
from nanfo_routing.contracts import Observation, Request
from nanfo_routing.env import encode
from nanfo_routing.ppo import PPO
from nanfo_routing.transport import TransportError


@pytest.mark.parametrize(
    "command",
    [None, "train", "evaluate", "infer", "inspect", "report", "plan", "qualify", "select"],
)
def test_cli_help_in_fresh_process(command):
    args = [sys.executable, "-m", "nanfo_routing"]
    if command:
        args.append(command)
    result = subprocess.run([*args, "--help"], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0 and "usage:" in result.stdout


def test_fresh_process_fixture_inference_and_live_cli_refusal(tmp_path, observation):
    # This is serialization/inference verification, NOT measured training evidence.
    agent = PPO()
    path = tmp_path / "offline-fixture.ptz"
    saveCheckpoint(
        path,
        agent,
        provenance="offline-fixture-not-trained-model",
        trainingSeeds=[],
        episodes=0,
        evidenceHash="0" * 64,
    )
    raw = tmp_path / "observation.json"
    raw.write_text(json.dumps(observation))
    expected = agent.model.decide(
        encode([Observation.model_validate(observation)]), deterministic=True
    )
    script = """
import json, sys
from pathlib import Path
from nanfo_routing.artifacts import loadCheckpoint
from nanfo_routing.contracts import Observation
from nanfo_routing.env import encode
agent, manifest = loadCheckpoint(Path(sys.argv[1]), requireMeasured=False)
obs = Observation.model_validate_json(Path(sys.argv[2]).read_bytes())
print(json.dumps({'decision': agent.model.decide(encode([obs]), deterministic=True),
                  'provenance': manifest.provenance}))
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(path), str(raw)],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    actual = json.loads(result.stdout)
    assert actual["decision"] == list(expected)
    assert actual["provenance"] == "offline-fixture-not-trained-model"
    refused = subprocess.run(
        [
            sys.executable,
            "-m",
            "nanfo_routing",
            "infer",
            "--checkpoint",
            str(path),
            "--history",
            str(raw),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert refused.returncode == 1
    assert "not a measured-trained model" in refused.stderr


def test_failed_live_contact_has_durable_artifacts_and_no_checkpoint(tmp_path, monkeypatch):
    class Unavailable:
        def __init__(self, *args):
            self.commands = []

        def exchange(self, request):
            self.commands.append(request.command)
            raise TransportError("unit-test unavailable service; no measurement supplied")

    monkeypatch.setattr(cli, "DockerTransport", Unavailable)
    output = tmp_path / "failed-session"
    assert cli.main(["train", "--operator-experiment", "--output", str(output)]) == 1
    summary = json.loads((output / "summary.json").read_bytes())
    evidence = (output / "evidence.jsonl").read_bytes()
    assert summary["status"] == "failed" and summary["invalid_windows"] == 1
    assert summary["valid_transitions"] == summary["updates"] == summary["transitions"] == 0
    assert summary["cleanup_error"] and not (output / "checkpoint.ptz").exists()
    assert summary["evidence_sha256"] == hashlib.sha256(evidence).hexdigest()
    assert [json.loads(line)["request"]["command"] for line in evidence.splitlines()[1:]] == [
        "reset",
        "close",
    ]


@pytest.mark.parametrize(
    "options",
    [
        ["train", "--seed", "2000"],
        ["evaluate", "--split", "validation", "--seed", "3000"],
        ["evaluate", "--policy", "ospf", "--mode", "sdn"],
        ["train", "--budget-seconds", "0"],
    ],
)
def test_invalid_session_never_contacts_docker(tmp_path, monkeypatch, options):
    def forbidden(*args):
        pytest.fail("invalid configuration contacted Docker")

    monkeypatch.setattr(cli, "DockerTransport", forbidden)
    assert cli.main([*options, "--operator-experiment", "--output", str(tmp_path / "run")]) == 1
    assert not (tmp_path / "run").exists()


def test_campaign_preserves_failure_without_inference_or_retry(tmp_path, monkeypatch):
    campaign = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts" / "campaign.py"))
    commands = []

    def failed(argv, **kwargs):
        commands.append(argv)
        return subprocess.CompletedProcess(argv, 1)

    monkeypatch.setattr(subprocess, "run", failed)
    output = tmp_path / "campaign"
    assert (
        campaign["main"](["--operator-experiment", "--baseline-verified", "--output", str(output)])
        == 1
    )
    summary = json.loads((output / "campaign.json").read_bytes())
    assert summary["status"] == "failed" and summary["requested_training_transitions"] == 24
    assert summary["held_out_evaluation"] == "not_run"
    assert not summary["convergence_established"] and len(commands) == 1
    assert (output / "train.stderr.log").exists()


def test_inference_validates_history_spec_and_order(tmp_path, monkeypatch, transport, capsys):
    frames = []
    for index in range(1):
        request = Request(
            command="reset" if index == 0 else "step",
            seed=1000,
            scenario="low",
            episode_id=None if index == 0 else frames[0]["response"]["data"]["episode_id"],
            step_index=index if index else None,
            action=index % 2 if index else None,
            episode_steps=4,
        )
        frames.append({"request": request.model_dump(), "response": transport.exchange(request)})
    agent = PPO()
    evidence = frames[0]["response"]["data"]["evidence"]
    manifest = saveCheckpoint(
        tmp_path / "fixture.ptz",
        agent,
        provenance="offline-fixture-not-trained-model",
        trainingSeeds=[],
        episodes=0,
        evidenceHash="0" * 64,
        environmentSpec=evidence["environment_spec"],
        labProvenance=evidence["provenance"],
        distribution=trainingDistribution(5.0, 4),
    )
    # Explicit unit-only loader injection; no mock is saved or reported as measured-trained.
    monkeypatch.setattr(cli, "loadCheckpoint", lambda path: (agent, manifest))
    path = tmp_path / "history.json"
    path.write_text(json.dumps({"version": 3, "frames": frames}))
    args = ["infer", "--checkpoint", str(tmp_path / "fixture.ptz"), "--history", str(path)]
    assert cli.main(args) == 0
    assert (
        json.loads(capsys.readouterr().out)["checkpoint_provenance"]
        == "offline-fixture-not-trained-model"
    )
    path.write_text(json.dumps({"version": 3, "frames": [frames[0], frames[0]]}))
    assert cli.main(args) == 1
    assert "invalid measured history" in capsys.readouterr().err
    path.write_text(json.dumps({"version": 2, "frames": [frames[-1]]}))
    assert cli.main(args) == 1
    assert "invalid measured history" in capsys.readouterr().err

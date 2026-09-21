"""Offline holdout supervisor tests. No network collection or trained fixture promotion."""

import importlib.util
from copy import deepcopy
from pathlib import Path

import pytest

from nanfo_routing.contracts import jsonBytes, parseJson

spec = importlib.util.spec_from_file_location(
    "holdout", Path(__file__).resolve().parents[1] / "scripts" / "run_adr014_holdout.py"
)
holdout = importlib.util.module_from_spec(spec)
spec.loader.exec_module(holdout)


def test_selection_reward_tie_earliest_and_all_candidates():
    rows = [
        {"transitions": n, "qualified": True, "validation_mean_reward": r}
        for n, r in ((128, 0.7), (256, 0.8), (384, 0.8))
    ]
    assert holdout.choose(rows)["transitions"] == 256
    rows[-1]["validation_mean_reward"] = 0.9
    assert holdout.choose(rows)["transitions"] == 384
    rows[-1]["qualified"] = False
    assert holdout.choose(rows)["transitions"] == 256
    with pytest.raises(ValueError, match="all original"):
        holdout.choose(rows[:2])


@pytest.mark.parametrize("failure", [False, True])
def test_session_consumes_once_and_only_frozen_test_args(tmp_path, monkeypatch, failure):
    plan = {
        "campaign_id": "a" * 32,
        "policy_order": ["ppo", "ospf"],
        "test_seeds": list(range(3900, 3912)),
        "checkpoint_path": "model.ptz",
        "checkpoint": {"checkpoint_sha256": "b" * 64},
    }
    (tmp_path / "plan.json").write_bytes(jsonBytes(plan))
    (tmp_path / "test-ledger.json").write_bytes(
        jsonBytes(
            {
                "plan_sha256": holdout.digest(tmp_path / "plan.json"),
                "deadline_unix": 1e12,
                "attempts": [],
            }
        )
    )
    monkeypatch.setattr(holdout, "verifiedPlan", lambda *a: deepcopy(plan))
    monkeypatch.setattr(holdout.signal, "signal", lambda *a: None)
    calls = []

    def run(args):
        calls.append(args)
        assert args.command == "evaluate" and args.split == "test"
        assert args.seed == 3900 and args.episodes == 12
        assert args.steps == 4 and args.window == 2.0 and args.mode == "matched"
        assert args.checkpoint == Path("model.ptz") and args.budget_seconds == 600
        assert not hasattr(args, "resume")
        if failure:
            raise ValueError("invalid measurement")
        return {"status": "completed"}

    monkeypatch.setattr(holdout.cli, "_runSession", run)
    if failure:
        with pytest.raises(ValueError, match="invalid measurement"):
            holdout.session(tmp_path, "ppo", "nanfo-training-" + "a" * 32)
    else:
        holdout.session(tmp_path, "ppo", "nanfo-training-" + "a" * 32)
    with pytest.raises(ValueError, match="no retry"):
        holdout.session(tmp_path, "ppo", "nanfo-training-" + "a" * 32)
    ledger = parseJson((tmp_path / "test-ledger.json").read_bytes())
    assert len(calls) == len(ledger["attempts"]) == 1
    assert ledger["attempts"][0]["status"] == ("attempted" if failure else "completed")
    assert "finished_unix" in ledger["attempts"][0]


def test_budget_and_ownership_refuse_before_measuring(tmp_path, monkeypatch):
    plan = {"campaign_id": "a" * 32, "policy_order": ["ospf"]}
    (tmp_path / "plan.json").write_bytes(jsonBytes(plan))
    (tmp_path / "test-ledger.json").write_bytes(
        jsonBytes(
            {
                "plan_sha256": holdout.digest(tmp_path / "plan.json"),
                "deadline_unix": 0,
                "attempts": [],
            }
        )
    )
    monkeypatch.setattr(holdout, "verifiedPlan", lambda *a: plan)
    with pytest.raises(ValueError, match="not owned"):
        holdout.session(tmp_path, "ospf", "nanfo-experiment")
    with pytest.raises(ValueError, match="exhausted"):
        holdout.session(tmp_path, "ospf", "nanfo-training-" + "a" * 32)


def test_holdout_has_one_hour_deadline_not_original_training_reserve(tmp_path, monkeypatch):
    # Constructor arithmetic is correct; arbitrary uptime floats can lose low bits.
    monkeypatch.setattr(holdout.time, "monotonic", lambda: 1024.25)
    runner = holdout.Holdout(tmp_path, {"campaign_id": "a" * 32, "checkpoint": {}})
    assert runner.hardDeadline - runner.started == 3600
    assert runner.workDeadline - runner.started == 3480


def test_preparation_fails_on_source_drift_before_qualification(monkeypatch):
    monkeypatch.setattr(holdout, "readJson", lambda *a: {"client_source_sha256": {}})
    monkeypatch.setattr(holdout, "clientSources", lambda: {"changed.py": "a" * 64})
    with pytest.raises(ValueError, match="frozen source"):
        holdout.prepare()

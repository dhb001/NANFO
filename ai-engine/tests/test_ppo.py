import copy
import hashlib
import io
import json
import zipfile

import numpy as np
import pytest
import torch

from nanfo_routing.artifacts import (
    EvidenceLog,
    checkDistribution,
    inspectCheckpoint,
    loadCheckpoint,
    saveCheckpoint,
    trainingDistribution,
)
from nanfo_routing.contracts import STATE_DIM, Observation
from nanfo_routing.env import encode
from nanfo_routing.ppo import PPO, PPOConfig, clippedObjective, generalizedAdvantage, seedRuntime


def offlineRollout(agent, state):
    rows = []
    for index in range(8):
        action, logProb, value, _ = agent.model.decide(state)
        rows.append(
            {
                "state": state,
                "action": action,
                "log_prob": logProb,
                "value": value,
                "next_value": value,
                "reward": 1.0 if index % 2 else -1.0,
                "terminated": False,
                "truncated": index == 7,
                "valid_transition": True,
            }
        )
    return rows


def test_gae_time_limit_bootstraps_and_stops_recursion():
    advantage, returns = generalizedAdvantage(
        [1, 2, 100],
        [0.5, 1, 0],
        [1, 4, 99],
        [False, False, True],
        [False, True, False],
        gamma=0.9,
        gaeLambda=0.8,
    )
    np.testing.assert_allclose(advantage, [1.4 + 0.72 * 4.6, 4.6, 100], rtol=1e-6)
    np.testing.assert_allclose(returns, advantage + torch.tensor([0.5, 1, 0]), rtol=1e-6)
    terminated, _ = generalizedAdvantage([2], [1], [4], [True], [False], gamma=0.9)
    assert terminated.item() == 1
    boundary, _ = generalizedAdvantage([2], [1], [4], [False], [False], gamma=0.9)
    assert boundary.item() == pytest.approx(4.6)


def test_ppo_clipping_both_advantage_signs():
    ratios = torch.tensor([1.5, 0.5, 1.5, 0.5])
    result = clippedObjective(ratios.log(), torch.zeros(4), torch.tensor([1, 1, -1, -1]), 0.2)
    torch.testing.assert_close(result, torch.tensor([1.2, 0.5, -1.5, -0.8]))


def test_fixture_weights_update_roundtrip_and_seeded_action(tmp_path, observation):
    agent = PPO(PPOConfig(epochs=2, rollout=8, minibatch=4))
    state = encode([Observation.model_validate(observation)])
    before = copy.deepcopy(agent.model.state_dict())
    metrics = agent.update(offlineRollout(agent, state))
    assert all(np.isfinite(list(metrics.values())))
    assert any(
        not torch.equal(before[key], value) for key, value in agent.model.state_dict().items()
    )
    path = tmp_path / "offline-fixture.ptz"
    saveCheckpoint(
        path,
        agent,
        provenance="offline-fixture-not-trained-model",
        trainingSeeds=[1000],
        episodes=1,
        evidenceHash=hashlib.sha256(b"fixture").hexdigest(),
    )
    seedRuntime(71)
    expected = agent.model.decide(state)
    loaded, manifest = loadCheckpoint(path, resume=True, requireMeasured=False)
    seedRuntime(71)
    assert loaded.model.decide(state) == expected
    assert manifest.transitions == 8 and manifest.updates == 1
    for key, value in agent.model.state_dict().items():
        torch.testing.assert_close(value, loaded.model.state_dict()[key], rtol=0, atol=0)
    assert (
        loaded.optimizer.state_dict()["param_groups"]
        == agent.optimizer.state_dict()["param_groups"]
    )
    assert inspectCheckpoint(path)["manifest"]["provenance"] == "offline-fixture-not-trained-model"
    with pytest.raises(ValueError, match="not a measured-trained"):
        loadCheckpoint(path)
    # Resumed optimizer moments and RNG produce exactly the same next update.
    seedRuntime(9)
    batch = offlineRollout(agent, state)
    seedRuntime(10)
    agent.update(batch)
    seedRuntime(10)
    loaded.update(batch)
    for key, value in agent.model.state_dict().items():
        torch.testing.assert_close(value, loaded.model.state_dict()[key], rtol=0, atol=0)


def test_invalid_transitions_never_update_weights():
    agent = PPO(PPOConfig(rollout=8))
    before = copy.deepcopy(agent.model.state_dict())
    rows = offlineRollout(agent, np.zeros(STATE_DIM, dtype=np.float32))
    rows[0]["valid_transition"] = False
    with pytest.raises(ValueError, match="invalid windows"):
        agent.update(rows)
    rows[0]["valid_transition"] = True
    rows[0]["reward"] = float("nan")
    with pytest.raises(ValueError, match="finite"):
        agent.update(rows)
    for key, value in agent.model.state_dict().items():
        assert torch.equal(value, before[key])


@pytest.mark.parametrize(
    "corruption",
    [
        "hash",
        "contract",
        "version",
        "seed",
        "shape",
        "nan",
        "optimizer",
        "extra",
        "pickle",
        "old_contract",
        "spec",
        "distribution",
        "client_source",
    ],
)
def test_checkpoint_rejects_corruption(tmp_path, corruption):
    path = tmp_path / "fixture.ptz"
    agent = PPO()
    saveCheckpoint(
        path,
        agent,
        provenance="offline-fixture-not-trained-model",
        trainingSeeds=[1000],
        episodes=1,
        evidenceHash="0" * 64,
    )
    with zipfile.ZipFile(path) as bundle:
        manifest = json.loads(bundle.read("manifest.json"))
        weights = bundle.read("weights.pt")
    if corruption == "hash":
        manifest["weights_sha256"] = "0" * 64
    elif corruption == "contract":
        manifest["contract"]["scales"][0] = 12
    elif corruption == "version":
        manifest["versions"]["torch"] = "untrusted"
    elif corruption == "seed":
        manifest["training_seeds"] = [3000]
    elif corruption == "extra":
        manifest["unsafe_config"] = "ignored?"
    elif corruption == "old_contract":
        manifest["version"] = 1
        manifest["contract_hash"] = (
            "f31b55139f5ad6e69b48ecd110ccdc31ed447b65f02ca518703232cc407b390a"
        )
    elif corruption == "spec":
        manifest["environment_spec"]["source"] = "changed producer"
    elif corruption == "distribution":
        manifest["training_distribution"]["episode_steps"] = 2
    elif corruption == "client_source":
        manifest["client_source_files"]["ppo.py"] = "0" * 64
    else:
        payload = torch.load(io.BytesIO(weights), weights_only=True)
        key = next(iter(payload["model"]))
        if corruption == "shape":
            payload["model"][key] = torch.zeros(1)
        elif corruption == "nan":
            payload["model"][key].fill_(float("nan"))
        elif corruption == "optimizer":
            payload["optimizer"]["param_groups"][0]["lr"] = 999
        else:
            payload["unsafe"] = PPOConfig()
        buffer = io.BytesIO()
        torch.save(payload, buffer)
        weights = buffer.getvalue()
        manifest["weights_sha256"] = hashlib.sha256(weights).hexdigest()
    with zipfile.ZipFile(path, "w") as bundle:
        bundle.writestr("manifest.json", json.dumps(manifest))
        bundle.writestr("weights.pt", weights)
    with pytest.raises(ValueError):
        loadCheckpoint(path, requireMeasured=False)


def test_evidence_bound_and_no_overwrite(tmp_path):
    path = tmp_path / "evidence.jsonl"
    log = EvidenceLog(path, limit=1024)
    log.append({"source": "offline fixture"})
    with pytest.raises(ValueError, match="capacity"):
        log.append({"data": "x" * 1024})
    with pytest.raises(ValueError):
        log.append({"reward": float("nan")})
    log.close()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == log.digest.hexdigest()
    with pytest.raises(FileExistsError):
        EvidenceLog(path)


def test_checkpoint_is_byte_stable_and_resumes_rng_without_reseeding(tmp_path):
    agent = PPO(PPOConfig(epochs=1, rollout=8))
    state = np.zeros(STATE_DIM, dtype=np.float32)
    agent.update(offlineRollout(agent, state))
    paths = [tmp_path / "one.ptz", tmp_path / "two.ptz"]
    for path in paths:
        saveCheckpoint(
            path,
            agent,
            provenance="offline-fixture-not-trained-model",
            trainingSeeds=[1000],
            episodes=1,
            evidenceHash="0" * 64,
        )
    assert paths[0].read_bytes() == paths[1].read_bytes()
    expected = [agent.model.decide(state) for _ in range(10)]
    loaded, _ = loadCheckpoint(paths[0], resume=True, requireMeasured=False)
    assert [loaded.model.decide(state) for _ in range(10)] == expected


def test_bad_archive_is_handled_without_unrestricted_fallback(tmp_path):
    path = tmp_path / "bad.ptz"
    path.write_bytes(b"not a checkpoint")
    with pytest.raises(ValueError, match="archive"):
        loadCheckpoint(path)


@pytest.mark.parametrize(
    "field,value", [("action", 0.5), ("action", True), ("terminated", 1), ("truncated", "false")]
)
def test_ppo_rejects_coerced_actions_and_masks(field, value):
    agent = PPO(PPOConfig(rollout=8))
    rows = offlineRollout(agent, np.zeros(STATE_DIM, dtype=np.float32))
    rows[0][field] = value
    with pytest.raises(ValueError, match="action or boundary"):
        agent.update(rows)
    assert agent.updates == 0


def test_checkpoint_distribution_requires_explicit_generalization(tmp_path):
    path = tmp_path / "fixture.ptz"
    manifest = saveCheckpoint(
        path,
        PPO(),
        provenance="offline-fixture-not-trained-model",
        trainingSeeds=[],
        episodes=0,
        evidenceHash="0" * 64,
        environmentSpec={"source": "offline unit fixture"},
        distribution=trainingDistribution(5.0, 4),
    )
    assert not checkDistribution(manifest, 5.0, 4)
    with pytest.raises(ValueError, match="generalization"):
        checkDistribution(manifest, 5.0, 2)
    assert checkDistribution(manifest, 5.0, 2, generalization=True)
    with pytest.raises(ValueError, match="generalization"):
        checkDistribution(manifest, 2.0, 4)


def test_ppo_diagnostics_and_zero_variance():
    agent = PPO(PPOConfig(rollout=8, gamma=0.0))
    rows = offlineRollout(agent, np.zeros(STATE_DIM, dtype=np.float32))
    for row in rows:
        row["reward"] = 1.0
    result = agent.update(rows)
    assert result["approximate_kl"] >= -1e-7
    assert 0 <= result["clip_fraction"] <= 1
    assert result["explained_variance"] is None

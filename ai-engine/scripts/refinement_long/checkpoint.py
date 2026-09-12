"""ADR016 tensor-only checkpoints with new namespace and optimizer-reset lineage."""

import hashlib
import io
import zipfile

import torch
from contract import declaration
from history import PARENT_HASH, a, c, digest, parent, ppo


def warmstart():
    reference, metadata = parent()
    agent = ppo.PPO(ppo.PPOConfig(**declaration()["ppo_config"]))
    agent.model.load_state_dict(reference.model.state_dict(), strict=True)
    return agent, metadata


def modelHash(agent):
    result = hashlib.sha256()
    for name, tensor in agent.model.state_dict().items():
        result.update(name.encode())
        result.update(tensor.detach().cpu().numpy().tobytes())
    return result.hexdigest()


def save(path, agent, plan, seeds, evidenceHashes):
    if path.exists():
        raise ValueError("checkpoint immutable")
    buffer = io.BytesIO()
    torch.save(
        {
            "model": agent.model.state_dict(),
            "optimizer": agent.optimizer.state_dict(),
            "torch_rng": torch.get_rng_state(),
        },
        buffer,
    )
    weights = buffer.getvalue()
    metadata = {
        "version": "adr016-checkpoint-v1",
        "parent_checkpoint_sha256": PARENT_HASH,
        "parent_manifest_sha256": plan["parent_manifest_sha256"],
        "initialization": plan["initialization"],
        "config": agent.config.model_dump(),
        "runtime": a.runtimeVersions(),
        "namespace": plan["seed_namespaces"],
        "feature_action_reward_contract": c.CONTRACT,
        "environment_spec": plan["release"]["environment_spec"],
        "plan_sha256": plan["plan_sha256"],
        "sources": plan["sources"],
        "training_seeds": seeds,
        "transitions": agent.transitions,
        "updates": agent.updates,
        "training_evidence_sha256": evidenceHashes,
        "weights_sha256": hashlib.sha256(weights).hexdigest(),
        "model_sha256": modelHash(agent),
    }
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as bundle:
        bundle.writestr(zipfile.ZipInfo("manifest.json"), c.jsonBytes(metadata))
        bundle.writestr(zipfile.ZipInfo("weights.pt"), weights)
    a.atomicWrite(path, archive.getvalue())
    return digest(path)


def load(path, sha, plan):
    if path.stat().st_size > a.MAX_CHECKPOINT or digest(path) != sha:
        raise ValueError("checkpoint size/hash mismatch")
    with zipfile.ZipFile(path) as bundle:
        entries = bundle.infolist()
        if (
            len(entries) != 2
            or {e.filename for e in entries} != {"manifest.json", "weights.pt"}
            or any(e.compress_type != zipfile.ZIP_STORED for e in entries)
            or sum(e.file_size for e in entries) > a.MAX_CHECKPOINT
        ):
            raise ValueError("invalid checkpoint archive")
        metadata = c.parseJson(bundle.read("manifest.json"))
        weights = bundle.read("weights.pt")
    required = {
        "version": "adr016-checkpoint-v1",
        "parent_checkpoint_sha256": PARENT_HASH,
        "parent_manifest_sha256": plan["parent_manifest_sha256"],
        "initialization": plan["initialization"],
        "config": plan["ppo_config"],
        "runtime": a.runtimeVersions(),
        "namespace": plan["seed_namespaces"],
        "feature_action_reward_contract": c.CONTRACT,
        "environment_spec": plan["release"]["environment_spec"],
        "plan_sha256": plan["plan_sha256"],
        "sources": plan["sources"],
    }
    if any(metadata.get(k) != v for k, v in required.items()):
        raise ValueError("checkpoint contract/runtime/lineage mismatch")
    count = metadata["transitions"]
    if (
        type(count) is not int
        or not 32 <= count <= 2048
        or count % 32
        or metadata["updates"] != count // 32
        or metadata["training_seeds"] != [r["seed"] for r in plan["training"][: count // 4]]
        or hashlib.sha256(weights).hexdigest() != metadata["weights_sha256"]
    ):
        raise ValueError("fresh training counters/seeds/weights mismatch")
    with zipfile.ZipFile(io.BytesIO(weights)) as bundle:
        entries = bundle.infolist()
        if (
            len(entries) > 256
            or sum(e.file_size for e in entries) > a.MAX_CHECKPOINT
            or any(e.compress_type != zipfile.ZIP_STORED for e in entries)
        ):
            raise ValueError("tensor archive exceeds bounds")
    payload = torch.load(io.BytesIO(weights), map_location="cpu", weights_only=True)
    agent = ppo.PPO(ppo.PPOConfig(**plan["ppo_config"]))
    expected = agent.model.state_dict()
    if set(payload) != {"model", "optimizer", "torch_rng"} or set(payload["model"]) != set(
        expected
    ):
        raise ValueError("model tensor keys differ")
    for name, reference in expected.items():
        value = payload["model"][name]
        if (
            not isinstance(value, torch.Tensor)
            or value.shape != reference.shape
            or value.dtype != reference.dtype
            or not torch.isfinite(value).all()
        ):
            raise ValueError("invalid model tensor")
    agent.model.load_state_dict(payload["model"], strict=True)
    if modelHash(agent) != metadata["model_sha256"]:
        raise ValueError("model digest mismatch")
    agent.model.eval()
    return agent, metadata

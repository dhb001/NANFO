"""Separate refinement checkpoints, explicit transfer, never incumbent overwrite."""

import hashlib
import io
import zipfile

import torch
from frozen import PARENT_HASH, digest, incumbent, module
from plan import declaration

a = module("artifacts")
c = module("contracts")


def warmstart():
    parent, metadata, _ = incumbent()
    agent = module("ppo").PPO(module("ppo").PPOConfig(**declaration()["ppo_config"]))
    agent.model.load_state_dict(parent.model.state_dict(), strict=True)
    return agent, metadata


def save(path, agent, plan, seeds, evidenceHashes):
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
    contract = {
        "version": "adr015-v5-transfer",
        "measured_features_actions_reward": c.CONTRACT,
        "profiles": plan["profiles"],
        "environment_spec": plan["release"]["environment_spec"],
    }
    metadata = {
        "version": "adr015-candidate-v1",
        "parent_checkpoint_sha256": PARENT_HASH,
        "parent_source_sha256": plan["parent_source_sha256"],
        "parent_environment_spec": plan["parent_environment_spec"],
        "transfer": declaration()["initialization"],
        "contract": contract,
        "contract_sha256": hashlib.sha256(c.jsonBytes(contract)).hexdigest(),
        "weights_sha256": hashlib.sha256(weights).hexdigest(),
        "config": agent.config.model_dump(),
        "runtime": a.runtimeVersions(),
        "refinement_sources": plan["refinement_sources"],
        "training_seeds": seeds,
        "evidence_sha256": evidenceHashes,
        "transitions": agent.transitions,
        "updates": agent.updates,
        "plan_sha256": plan["plan_sha256"],
    }
    bundle = io.BytesIO()
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr(zipfile.ZipInfo("manifest.json"), c.jsonBytes(metadata))
        archive.writestr(zipfile.ZipInfo("weights.pt"), weights)
    if path.exists():
        raise ValueError("candidate checkpoint is immutable")
    a.atomicWrite(path, bundle.getvalue())
    return digest(path)


def load(path, expectedHash, plan):
    if path.stat().st_size > a.MAX_CHECKPOINT or digest(path) != expectedHash:
        raise ValueError("candidate hash/size mismatch")
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        if (
            len(entries) != 2
            or {e.filename for e in entries} != {"manifest.json", "weights.pt"}
            or sum(e.file_size for e in entries) > a.MAX_CHECKPOINT
            or any(e.compress_type != zipfile.ZIP_STORED for e in entries)
        ):
            raise ValueError("invalid candidate archive")
        metadata = c.parseJson(archive.read("manifest.json"))
        weights = archive.read("weights.pt")
    if (
        metadata["version"] != "adr015-candidate-v1"
        or metadata["parent_checkpoint_sha256"] != PARENT_HASH
        or metadata["parent_source_sha256"] != plan["parent_source_sha256"]
        or metadata["parent_environment_spec"] != plan["parent_environment_spec"]
        or metadata["transfer"] != declaration()["initialization"]
        or metadata["runtime"] != a.runtimeVersions()
        or metadata["config"] != plan["ppo_config"]
        or metadata["refinement_sources"] != plan["refinement_sources"]
        or metadata["plan_sha256"] != plan["plan_sha256"]
        or metadata["contract"]["environment_spec"] != plan["release"]["environment_spec"]
        or metadata["contract"]["measured_features_actions_reward"] != c.CONTRACT
        or metadata["contract"]["profiles"] != plan["profiles"]
        or hashlib.sha256(c.jsonBytes(metadata["contract"])).hexdigest()
        != metadata["contract_sha256"]
        or hashlib.sha256(weights).hexdigest() != metadata["weights_sha256"]
    ):
        raise ValueError("candidate manifest differs from frozen refinement")
    if (
        type(metadata["transitions"]) is not int
        or metadata["transitions"] % 16
        or not 16 <= metadata["transitions"] <= 512
        or metadata["updates"] != metadata["transitions"] // 16
        or metadata["training_seeds"]
        != [r["seed"] for r in plan["training"][: metadata["transitions"] // 4]]
    ):
        raise ValueError("candidate fresh training lineage differs")
    with zipfile.ZipFile(io.BytesIO(weights)) as archive:
        if (
            len(archive.infolist()) > 256
            or sum(e.file_size for e in archive.infolist()) > a.MAX_CHECKPOINT
            or any(e.compress_type != zipfile.ZIP_STORED for e in archive.infolist())
        ):
            raise ValueError("candidate tensor archive exceeds bounds")
    payload = torch.load(io.BytesIO(weights), map_location="cpu", weights_only=True)
    agent = module("ppo").PPO(module("ppo").PPOConfig(**metadata["config"]))
    expected = agent.model.state_dict()
    if set(payload) != {"model", "optimizer", "torch_rng"} or set(payload["model"]) != set(
        expected
    ):
        raise ValueError("candidate tensor keys mismatch")
    for name, ref in expected.items():
        tensor = payload["model"][name]
        if (
            not isinstance(tensor, torch.Tensor)
            or tensor.shape != ref.shape
            or tensor.dtype != ref.dtype
            or not torch.isfinite(tensor).all()
        ):
            raise ValueError("invalid candidate tensor")
    agent.model.load_state_dict(payload["model"], strict=True)
    agent.model.eval()
    return agent, metadata

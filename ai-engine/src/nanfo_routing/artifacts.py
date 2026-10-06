"""Bounded evidence and atomic, tensor-only checkpoint bundles with JSON manifests."""

import hashlib
import io
import json
import os
import pickle
import platform
import re
import stat
import tempfile
import zipfile
from pathlib import Path
from typing import Annotated, Literal

import gymnasium
import numpy as np
import torch
from pydantic import Field

from . import __version__
from .contracts import (
    CONTRACT,
    CONTRACT_HASH,
    Request,
    StrictModel,
    jsonBytes,
    parseJson,
    validateSeed,
)
from .evidence import validateSpec
from .ppo import PPO, PPOConfig

MAX_CHECKPOINT = 16 * 1024 * 1024
MAX_MANIFEST = 128 * 1024
MAX_EVIDENCE = 64 * 1024 * 1024


class EvidenceLog:
    def __init__(self, path: Path, limit=MAX_EVIDENCE):
        if not 1024 <= limit <= MAX_EVIDENCE:
            raise ValueError("evidence bound outside limits")
        self.file = path.open("xb")
        self.limit = limit
        self.size = 0
        self.digest = hashlib.sha256()

    def append(self, value):
        encoded = jsonBytes(value) + b"\n"
        if len(encoded) > 2 * 1024 * 1024 or self.size + len(encoded) > self.limit:
            raise ValueError("evidence capacity exhausted; stop experiment")
        self.file.write(encoded)
        self.file.flush()
        os.fsync(self.file.fileno())
        self.digest.update(encoded)
        self.size += len(encoded)

    def close(self):
        if not self.file.closed:
            self.file.flush()
            os.fsync(self.file.fileno())
            self.file.close()


def atomicWrite(path: Path, content: bytes):
    if len(content) > MAX_CHECKPOINT:
        raise ValueError("artifact too large")
    fd, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class Manifest(StrictModel):
    version: Literal[3] = 3
    contract_hash: str
    contract: dict
    config: PPOConfig
    provenance: Literal["measured-lab", "offline-fixture-not-trained-model"]
    training_seeds: Annotated[list[int], Field(max_length=1000)]
    updates: Annotated[int, Field(ge=0, le=10**9)]
    transitions: Annotated[int, Field(ge=0, le=10**9)]
    episodes: Annotated[int, Field(ge=0, le=1000)]
    versions: dict[str, str]
    weights_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    evidence_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    environment_spec: dict
    spec_hash: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    training_distribution: dict
    compatibility_hash: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    lab_provenance: dict
    client_source_files: dict[str, str]


def clientSources():
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(Path(__file__).parent.glob("*.py"))
    }


def compatibilityHash(spec, distribution):
    return hashlib.sha256(
        jsonBytes(
            {
                "contract_hash": CONTRACT_HASH,
                "environment_spec": spec,
                "spec_hash": hashlib.sha256(jsonBytes(spec)).hexdigest(),
                "training_distribution": distribution,
            }
        )
    ).hexdigest()


def trainingDistribution(window, steps, scenarios=("path0", "path1")):
    if list(scenarios) not in (["path0", "path1"], ["path1", "path0"]):
        raise ValueError("stationary curriculum requires balanced path0,path1")
    Request(
        command="reset", seed=1000, scenario="path0", window_seconds=window, episode_steps=steps
    )
    return {
        "mode": "matched",
        "window_seconds": window,
        "episode_steps": steps,
        "scenario_selection": "episode index modulo explicit balanced stationary curriculum",
        "scenarios": list(scenarios),
        "training_split": CONTRACT["splits"]["train"],
    }


def checkDistribution(manifest, window, steps, *, generalization=False, scenarios=None):
    different = (
        trainingDistribution(
            window, steps, scenarios or manifest.training_distribution["scenarios"]
        )
        != manifest.training_distribution
    )
    if different and not generalization:
        raise ValueError(
            "window/horizon differs from training; evaluation requires --generalization"
        )
    return different


def runtimeVersions():
    return {
        "python": platform.python_version(),
        "torch": str(torch.__version__),
        "numpy": np.__version__,
        "gymnasium": gymnasium.__version__,
        "package": __version__,
    }


def saveCheckpoint(
    path: Path,
    agent: PPO,
    *,
    provenance: str,
    trainingSeeds: list[int],
    episodes: int,
    evidenceHash: str,
    environmentSpec: dict | None = None,
    distribution: dict | None = None,
    labProvenance: dict | None = None,
) -> Manifest:
    if environmentSpec is None or distribution is None:
        if provenance == "measured-lab":
            raise ValueError("measured checkpoint requires lab spec and training distribution")
        environmentSpec = {"source": "offline unit fixture"}
        distribution = trainingDistribution(5.0, 4)
    if provenance == "measured-lab" and labProvenance is None:
        raise ValueError("measured checkpoint requires lab provenance")
    if len(set(trainingSeeds)) != len(trainingSeeds) or episodes != len(trainingSeeds):
        raise ValueError("invalid training seed metadata")
    for seed in trainingSeeds:
        validateSeed("train", seed)
    payload = {
        "model": agent.model.state_dict(),
        "optimizer": agent.optimizer.state_dict(),
        "torch_rng": torch.get_rng_state(),
    }
    buffer = io.BytesIO()
    torch.save(payload, buffer)
    tensors = buffer.getvalue()
    manifest = Manifest(
        contract_hash=CONTRACT_HASH,
        contract=CONTRACT,
        config=agent.config,
        provenance=provenance,
        training_seeds=trainingSeeds,
        updates=agent.updates,
        transitions=agent.transitions,
        episodes=episodes,
        versions=runtimeVersions(),
        weights_sha256=hashlib.sha256(tensors).hexdigest(),
        evidence_sha256=evidenceHash,
        environment_spec=environmentSpec,
        spec_hash=hashlib.sha256(jsonBytes(environmentSpec)).hexdigest(),
        training_distribution=distribution,
        compatibility_hash=compatibilityHash(environmentSpec, distribution),
        lab_provenance=labProvenance or {"source": "offline unit fixture"},
        client_source_files=clientSources(),
    )
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as bundle:
        # Fixed ZIP timestamps make identical snapshots byte-stable across wall time.
        bundle.writestr(zipfile.ZipInfo("manifest.json"), jsonBytes(manifest.model_dump()))
        bundle.writestr(zipfile.ZipInfo("weights.pt"), tensors)
    atomicWrite(path, archive.getvalue())
    return manifest


def readCheckpoint(path: Path):
    """The only checkpoint read: bounded, regular file, final symlink refused."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    with os.fdopen(fd, "rb") as source:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
            raise ValueError("checkpoint must be a regular file")
        content = source.read(MAX_CHECKPOINT + 1)
    if len(content) > MAX_CHECKPOINT:
        raise ValueError("checkpoint exceeds bound")
    return content


def readBundle(path: Path):
    return bundleManifest(readCheckpoint(path))


def bundleManifest(content: bytes):
    with zipfile.ZipFile(io.BytesIO(content)) as bundle:
        entries = bundle.infolist()
        if (
            len(entries) != 2
            or {entry.filename for entry in entries} != {"manifest.json", "weights.pt"}
            or any(entry.compress_type != zipfile.ZIP_STORED for entry in entries)
            or sum(entry.file_size for entry in entries) > MAX_CHECKPOINT
            or bundle.getinfo("manifest.json").file_size > MAX_MANIFEST
        ):
            raise ValueError("invalid checkpoint bundle")
        metadata = parseJson(bundle.read("manifest.json"))
        if type(metadata) is not dict or metadata.get("version") != 3:
            raise ValueError("incompatible checkpoint version; v3 requires fresh training, not v2")
        manifest = Manifest.model_validate(metadata)
        tensors = bundle.read("weights.pt")
    if manifest.contract_hash != CONTRACT_HASH or jsonBytes(manifest.contract) != jsonBytes(
        CONTRACT
    ):
        raise ValueError("incompatible topology/features/reward/split contract")
    if manifest.versions != runtimeVersions():
        raise ValueError("runtime version mismatch; use the pinned checkpoint runtime")
    if manifest.client_source_files != clientSources():
        raise ValueError("client source differs from checkpoint; use frozen training source")
    if (
        hashlib.sha256(jsonBytes(manifest.environment_spec)).hexdigest() != manifest.spec_hash
        or compatibilityHash(manifest.environment_spec, manifest.training_distribution)
        != manifest.compatibility_hash
    ):
        raise ValueError("environment/distribution compatibility hash mismatch")
    if manifest.provenance == "measured-lab":
        validateSpec(manifest.environment_spec, manifest.spec_hash)
    distribution = manifest.training_distribution
    if distribution != trainingDistribution(
        distribution.get("window_seconds"),
        distribution.get("episode_steps"),
        distribution.get("scenarios", []),
    ):
        raise ValueError("invalid training distribution")
    if hashlib.sha256(tensors).hexdigest() != manifest.weights_sha256:
        raise ValueError("checkpoint weight digest mismatch")
    if len(set(manifest.training_seeds)) != len(
        manifest.training_seeds
    ) or manifest.episodes != len(manifest.training_seeds):
        raise ValueError("invalid training seed metadata")
    for seed in manifest.training_seeds:
        validateSeed("train", seed)
    if (
        not 2 * manifest.updates
        <= manifest.transitions
        <= manifest.config.rollout * manifest.updates
    ):
        raise ValueError("inconsistent training counters")
    return manifest, tensors


def loadCheckpointIdentity(path: Path, *, expectedSha256=None, resume=False, requireMeasured=True):
    """Load the exact bytes whose SHA-256 is returned, after an optional external pin.

    The pin is checked before any archive or tensor parsing; weights are restored with
    torch.load(weights_only=True) from those same in-memory bytes, never a second read.
    """
    if expectedSha256 is not None and (
        type(expectedSha256) is not str or not re.fullmatch(r"[a-f0-9]{64}", expectedSha256)
    ):
        raise ValueError("invalid checkpoint pin")
    content = readCheckpoint(path)
    digest = hashlib.sha256(content).hexdigest()
    if expectedSha256 is not None and digest != expectedSha256:
        raise ValueError("checkpoint differs from its pinned SHA-256")
    agent, manifest = restoreCheckpoint(content, resume=resume, requireMeasured=requireMeasured)
    return (
        agent,
        manifest,
        {
            "checkpoint_sha256": digest,
            "manifest": json.loads(manifest.model_dump_json()),
        },
    )


def loadCheckpoint(path: Path, *, resume=False, requireMeasured=True, expectedSha256=None):
    agent, manifest, _ = loadCheckpointIdentity(
        path, expectedSha256=expectedSha256, resume=resume, requireMeasured=requireMeasured
    )
    return agent, manifest


def restoreCheckpoint(content: bytes, *, resume=False, requireMeasured=True):
    try:
        manifest, tensors = bundleManifest(content)
    except (zipfile.BadZipFile, EOFError, KeyError) as exc:
        raise ValueError("invalid checkpoint archive") from exc
    if requireMeasured and (
        manifest.provenance != "measured-lab" or manifest.transitions < 2 or manifest.updates < 1
    ):
        raise ValueError("checkpoint is not a measured-trained model")
    # Never deserialize config/classes from pickle. All metadata is validated JSON.
    try:
        with zipfile.ZipFile(io.BytesIO(tensors)) as archive:
            if (
                len(archive.infolist()) > 256
                or any(row.compress_type != zipfile.ZIP_STORED for row in archive.infolist())
                or sum(row.file_size for row in archive.infolist()) > MAX_CHECKPOINT
            ):
                raise ValueError("tensor archive exceeds bounds")
        payload = torch.load(io.BytesIO(tensors), map_location="cpu", weights_only=True)
    except (
        pickle.UnpicklingError,
        RuntimeError,
        EOFError,
        KeyError,
        IndexError,
        zipfile.BadZipFile,
    ) as exc:
        raise ValueError("invalid restricted tensor payload") from exc
    if type(payload) is not dict or set(payload) != {"model", "optimizer", "torch_rng"}:
        raise ValueError("invalid tensor payload")
    agent = PPO(manifest.config)
    expected = agent.model.state_dict()
    if type(payload["model"]) not in (dict, type(expected)) or set(payload["model"]) != set(
        expected
    ):
        raise ValueError("model keys mismatch")
    for name, reference in expected.items():
        value = payload["model"][name]
        if (
            not isinstance(value, torch.Tensor)
            or value.shape != reference.shape
            or value.dtype != reference.dtype
            or not torch.isfinite(value).all()
        ):
            raise ValueError("invalid model tensor")
    optimizer = payload["optimizer"]
    if type(optimizer) is not dict or set(optimizer) != {"state", "param_groups"}:
        raise ValueError("invalid optimizer state")
    groups = optimizer["param_groups"]
    expectedGroup = agent.optimizer.state_dict()["param_groups"]
    if type(groups) is not list or len(groups) != 1 or type(groups[0]) is not dict:
        raise ValueError("invalid optimizer groups")
    try:
        groupsMatch = json.dumps(groups, sort_keys=True, allow_nan=False) == json.dumps(
            expectedGroup, sort_keys=True, allow_nan=False
        )
    except (ValueError, TypeError) as exc:
        raise ValueError("invalid optimizer hyperparameters") from exc
    if not groupsMatch:
        raise ValueError("optimizer hyperparameters mismatch")
    state = optimizer["state"]
    parameters = list(agent.model.parameters())
    expectedIds = set(range(len(parameters))) if manifest.updates else set()
    if type(state) is not dict or set(state) != expectedIds:
        raise ValueError("optimizer parameter mapping mismatch")
    for index, moments in state.items():
        if type(moments) is not dict or set(moments) != {"step", "exp_avg", "exp_avg_sq"}:
            raise ValueError("invalid optimizer moments")
        for name, value in moments.items():
            shape = torch.Size([]) if name == "step" else parameters[index].shape
            if (
                not isinstance(value, torch.Tensor)
                or value.shape != shape
                or value.dtype != torch.float32
                or not torch.isfinite(value).all()
                or (name != "exp_avg" and (value < 0).any())
                or (name == "step" and (value < 1 or value != value.floor()))
            ):
                raise ValueError("invalid optimizer tensor")
    if state and len({float(moments["step"]) for moments in state.values()}) != 1:
        raise ValueError("inconsistent optimizer step counters")
    rng = payload["torch_rng"]
    if (
        not isinstance(rng, torch.Tensor)
        or rng.dtype != torch.uint8
        or rng.shape != torch.get_rng_state().shape
    ):
        raise ValueError("invalid RNG tensor")
    previousRng = torch.get_rng_state()
    try:
        torch.set_rng_state(rng)
    except RuntimeError as exc:
        raise ValueError("invalid RNG state") from exc
    finally:
        torch.set_rng_state(previousRng)
    agent.model.load_state_dict(payload["model"], strict=True)
    agent.updates, agent.transitions = manifest.updates, manifest.transitions
    if resume:
        agent.optimizer.load_state_dict(optimizer)
        torch.set_rng_state(rng)
    agent.model.eval()
    return agent, manifest


def inspectCheckpoint(path: Path, *, expectedSha256=None):
    # Inspection also validates tensor shapes/finite values without enabling fixture inference;
    # the reported hash identifies exactly the bytes that were validated.
    _, _, identity = loadCheckpointIdentity(
        path, expectedSha256=expectedSha256, requireMeasured=False
    )
    return identity

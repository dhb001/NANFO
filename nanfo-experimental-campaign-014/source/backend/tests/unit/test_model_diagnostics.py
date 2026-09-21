"""Strict registry scope and real frozen measured replay, without touching AI files."""

import hashlib
from builtins import ExceptionGroup
import json
from pathlib import Path
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.modules.autonomy.model_diagnostic_schemas import DiagnoseModelRequest, ModelDiagnosticRegistry
from app.modules.autonomy.model_diagnostics import ModelDiagnosticsService, frozen_inference
from scripts.frozen_model_diagnostic import load_registry, select_model
from tests.model_diagnostic_support import CHECKPOINT_HASH, provision_registry


@pytest.fixture
def registered(tmp_path, monkeypatch):
    network_id = uuid.uuid4()
    env, document = provision_registry(tmp_path, network_id)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    registry, pin, _ = load_registry()
    return network_id, registry.models[0], pin, env, document


@pytest.mark.parametrize("reference", ["../history.json", "/etc/passwd", "a/b", "history.json", "", "a" * 81])
def test_client_reference_is_id_not_path(reference):
    with pytest.raises(ValidationError):
        DiagnoseModelRequest(network_id=uuid.uuid4(), history_reference=reference)


def test_client_cannot_supply_model_paths_or_vectors():
    for key in ("checkpoint", "model_id", "history", "source_directory", "observation", "vector"):
        with pytest.raises(ValidationError):
            DiagnoseModelRequest.model_validate({"network_id": str(uuid.uuid4()), "history_reference": "history", key: []})


def test_registry_scopes_and_permission_bits(registered):
    network, model, _, env, document = registered
    registry = ModelDiagnosticRegistry.model_validate(document)
    assert select_model(registry, network) == model
    assert select_model(registry, uuid.uuid4()) is None
    document["models"][0]["histories"]["validation-06"]["network_ids"] = [str(uuid.uuid4())]
    with pytest.raises(ValidationError):
        ModelDiagnosticRegistry.model_validate(document)
    Path(env["NANFO_MODEL_REGISTRY"]).chmod(0o666)
    with pytest.raises(ValueError, match="not_protected"):
        load_registry()


def test_registry_hash_tampering(registered):
    _, _, _, env, _ = registered
    path = Path(env["NANFO_MODEL_REGISTRY"])
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="hash_mismatch"):
        load_registry()


async def test_real_frozen_replay(registered):
    network, model, pin, _, _ = registered
    first = await frozen_inference(network, model, "validation-06", pin)
    second = await frozen_inference(network, model, "validation-06", pin)
    assert first.policy_sha256 == CHECKPOINT_HASH
    assert first.action == second.action == 0
    assert first.value == second.value == 3.2172513008117676
    assert first.probabilities == second.probabilities == [0.9718289375305176, 0.028171034529805183]
    assert first.input_sha256 == second.input_sha256 == "ea3a62d0a12bbc608b75b49b10a294bbcaeb2ec9ce276f07965d490352c5729a"
    assert not first.live and not first.safety_authorized and first.execution == "not_applied"
    assert first.subprocess_seconds > first.inference_seconds > 0


@pytest.mark.parametrize("tamper", ["history_hash", "history_path", "source_hash", "checkpoint_hash", "vector_only", "measured_evidence"])
async def test_real_runner_denies_tampered_artifacts(registered, monkeypatch, tmp_path, tamper):
    network, _, _, env, document = registered
    row = document["models"][0]
    if tamper == "history_hash":
        row["histories"]["validation-06"]["artifact"]["sha256"] = "0" * 64
    elif tamper == "history_path":
        row["histories"]["validation-06"]["artifact"]["path"] = "../../etc/passwd"
    elif tamper == "source_hash":
        row["source_sha256"]["__init__.py"] = "0" * 64
    elif tamper == "checkpoint_hash":
        row["checkpoint"]["sha256"] = "0" * 64
    else:
        # Copy verified inputs only into a new disposable producer root.
        root = tmp_path / "artifacts"
        root.mkdir()
        original = Path(env["NANFO_MODEL_ROOT"])
        refs = [row["checkpoint"], row["benchmark"]["evidence"], row["histories"]["validation-06"]["artifact"]]
        for ref in refs:
            target = root / ref["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((original / ref["path"]).read_bytes())
        source = root / row["source_directory"]
        source.mkdir(parents=True)
        for name in row["source_sha256"]:
            (source / name).write_bytes((original / row["source_directory"] / name).read_bytes())
        ref = row["histories"]["validation-06"]["artifact"]
        if tamper == "vector_only":
            content = json.dumps({"observation": [0] * 16}).encode()
        else:
            history = json.loads((root / ref["path"]).read_bytes())
            history["frames"][-1]["response"]["data"]["observation"]["goodput_mbps"] += 1
            content = json.dumps(history).encode()
        (root / ref["path"]).write_bytes(content)
        ref.update(sha256=hashlib.sha256(content).hexdigest(), size_bytes=len(content))
        monkeypatch.setenv("NANFO_MODEL_ROOT", str(root))
    content = json.dumps(document).encode()
    Path(env["NANFO_MODEL_REGISTRY"]).write_bytes(content)
    pin = hashlib.sha256(content).hexdigest()
    monkeypatch.setenv("NANFO_MODEL_REGISTRY_SHA256", pin)
    model = ModelDiagnosticRegistry.model_validate(document).models[0]
    with pytest.raises(ValueError, match="validation_failed"):
        await frozen_inference(network, model, "validation-06", pin)


@pytest.mark.parametrize("failure", ["timeout", "output_limit", "cancelled"])
async def test_child_is_reaped_on_bounded_failure(registered, monkeypatch, failure):
    import asyncio

    network, model, pin, _, _ = registered
    stdout = asyncio.StreamReader()
    stderr = asyncio.StreamReader()
    stderr.feed_eof()
    if failure == "output_limit":
        stdout.feed_data(b"x" * (64 * 1024 + 1))
        stdout.feed_eof()
    process = SimpleNamespace(returncode=None, stdout=stdout, stderr=stderr, wait=AsyncMock())
    process.kill = MagicMock(side_effect=lambda: setattr(process, "returncode", -9))
    monkeypatch.setattr(asyncio, "create_subprocess_exec", AsyncMock(return_value=process))
    original_timeout = asyncio.timeout
    monkeypatch.setattr(asyncio, "timeout", lambda _: original_timeout(0.01))
    if failure == "cancelled":
        task = asyncio.create_task(frozen_inference(network, model, "validation-06", pin))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        with pytest.raises((TimeoutError, ExceptionGroup)):
            await frozen_inference(network, model, "validation-06", pin)
    process.kill.assert_called_once()
    assert process.wait.await_count >= 1


async def test_child_environment_is_allowlisted(registered, monkeypatch):
    import asyncio

    network, model, pin, _, _ = registered
    monkeypatch.setenv("POSTGRES_PASSWORD", "must-not-reach-child")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "must-not-reach-child")
    monkeypatch.setenv("PYTHONPATH", "/untrusted")
    spawn = AsyncMock(side_effect=OSError("test spawn denied"))
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    with pytest.raises(OSError):
        await frozen_inference(network, model, "validation-06", pin)
    env = spawn.call_args.kwargs["env"]
    assert not {"POSTGRES_PASSWORD", "AWS_SECRET_ACCESS_KEY", "PYTHONPATH", "PATH"} & env.keys()
    assert spawn.call_args.args[1:3] == ("-I", "-B")


@pytest.mark.parametrize("change", ["revoked", "workspace", "registry"])
async def test_authority_rechecked_after_inference(registered, monkeypatch, change):
    network, model, pin, _, _ = registered
    lock = SimpleNamespace(acquire=AsyncMock(return_value=True), owned=AsyncMock(return_value=True), release=AsyncMock())
    redis = SimpleNamespace(lock=MagicMock(return_value=lock))
    db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock(), expire_all=MagicMock())
    service = ModelDiagnosticsService(db, redis)
    workspace = uuid.uuid4()
    service.scope = AsyncMock(side_effect=[workspace,
        HTTPException(403) if change == "revoked" else uuid.uuid4() if change == "workspace" else workspace])
    service.repo.insert = AsyncMock()
    async def infer(*args):
        if change == "registry":
            registry = ModelDiagnosticRegistry(version=1, models=[model])
            monkeypatch.setattr("app.modules.autonomy.model_diagnostics.load_registry", lambda: (registry, "f" * 64, None))
        return object()
    monkeypatch.setattr("app.modules.autonomy.model_diagnostics.frozen_inference", infer)
    with pytest.raises(HTTPException) as error:
        await service.diagnose(SimpleNamespace(user_id="actor"), DiagnoseModelRequest(network_id=network, history_reference="validation-06"))
    assert error.value.status_code == (403 if change == "revoked" else 409)
    service.repo.insert.assert_not_awaited()
    lock.release.assert_awaited_once()


async def test_current_network_scope_blocks_unregistered_history(registered):
    network, _, _, _, _ = registered
    db = SimpleNamespace(commit=AsyncMock())
    service = ModelDiagnosticsService(db, SimpleNamespace(lock=MagicMock()))
    service.scope = AsyncMock(return_value=uuid.uuid4())
    for target, reference in ((uuid.uuid4(), "validation-06"), (network, "unknown")):
        with pytest.raises(HTTPException) as error:
            await service.diagnose(SimpleNamespace(user_id="admin"), DiagnoseModelRequest(network_id=target, history_reference=reference))
        assert error.value.status_code == 404
    service.redis.lock.assert_not_called()

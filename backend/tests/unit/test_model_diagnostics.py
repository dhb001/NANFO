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
    service.org_scope = AsyncMock(return_value=uuid.uuid4())
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
    assert lock.release.await_count == 2  # per-network lock and the organization slot


async def test_current_network_scope_blocks_unregistered_history(registered):
    network, _, _, _, _ = registered
    db = SimpleNamespace(commit=AsyncMock())
    service = ModelDiagnosticsService(db, SimpleNamespace(lock=MagicMock()))
    service.scope = AsyncMock(return_value=uuid.uuid4())
    service.org_scope = AsyncMock(return_value=uuid.uuid4())
    for target, reference in ((uuid.uuid4(), "validation-06"), (network, "unknown")):
        with pytest.raises(HTTPException) as error:
            await service.diagnose(SimpleNamespace(user_id="admin"), DiagnoseModelRequest(network_id=target, history_reference=reference))
        assert error.value.status_code == 404
    service.redis.lock.assert_not_called()


# ── ADR-028 C26: per-network admission and per-organisation fairness ──────────


@pytest.fixture
def fair(monkeypatch, fake_redis):
    """Synthetic registry seam (no private artifacts): real Redis locks, fake frozen runner."""
    networks = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]
    history = SimpleNamespace(network_ids=networks)
    model = SimpleNamespace(histories={"validation-06": history})
    monkeypatch.setattr("app.modules.autonomy.model_diagnostics.load_registry", lambda: (object(), "f" * 64, None))
    monkeypatch.setattr("app.modules.autonomy.model_diagnostics.select_model", lambda registry, network: model)
    release = {}
    started = {}
    async def infer(network, *args):
        started[network] = True
        release.setdefault(network, __import__("asyncio").Event())
        await release[network].wait()
        return SimpleNamespace(network=network)
    monkeypatch.setattr("app.modules.autonomy.model_diagnostics.frozen_inference", infer)
    orgs = {networks[0]: "org-a", networks[1]: "org-a", networks[2]: "org-b"}
    def service():
        db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock(), expire_all=MagicMock())
        instance = ModelDiagnosticsService(db, fake_redis)
        instance.repo.insert = AsyncMock(side_effect=lambda **kwargs: kwargs["result"])
        current = {}
        async def scope(claims, network_id, write=False):
            current["network"] = network_id
            return uuid.UUID(int=1)
        instance.scope = scope
        instance.org_scope = AsyncMock(side_effect=lambda workspace: orgs[current["network"]])
        return instance
    return SimpleNamespace(networks=networks, service=service, release=release, started=started, redis=fake_redis)


def request(network):
    return DiagnoseModelRequest(network_id=network, history_reference="validation-06")


async def test_busy_network_is_refused_but_other_networks_proceed(fair, monkeypatch):
    import asyncio

    monkeypatch.setattr("app.modules.autonomy.model_diagnostics.max_per_org", lambda: 2)
    claims = SimpleNamespace(user_id="u")
    first = asyncio.create_task(fair.service().diagnose(claims, request(fair.networks[0])))
    while fair.networks[0] not in fair.started:
        await asyncio.sleep(0)
    with pytest.raises(HTTPException) as error:
        await fair.service().diagnose(claims, request(fair.networks[0]))
    assert error.value.status_code == 429 and error.value.detail["code"] == "MODEL_DIAGNOSTIC_BUSY"
    assert error.value.headers["Retry-After"]
    second = asyncio.create_task(fair.service().diagnose(claims, request(fair.networks[2])))
    while fair.networks[2] not in fair.started:
        await asyncio.sleep(0)
    for event in fair.release.values():
        event.set()
    assert (await first).network == fair.networks[0] and (await second).network == fair.networks[2]
    assert await fair.redis.keys("nanfo:autonomy:model-diagnostics:inference") == []


async def test_org_limit_is_per_organization(fair, monkeypatch):
    import asyncio

    monkeypatch.setattr("app.modules.autonomy.model_diagnostics.max_per_org", lambda: 1)
    claims = SimpleNamespace(user_id="u")
    first = asyncio.create_task(fair.service().diagnose(claims, request(fair.networks[0])))
    while fair.networks[0] not in fair.started:
        await asyncio.sleep(0)
    with pytest.raises(HTTPException) as error:  # same organisation, different network
        await fair.service().diagnose(claims, request(fair.networks[1]))
    assert error.value.status_code == 429 and error.value.detail["code"] == "MODEL_DIAGNOSTIC_ORG_LIMIT"
    assert not await fair.redis.exists(f"nanfo:autonomy:model-diagnostics:inference:{fair.networks[1]}")
    other = asyncio.create_task(fair.service().diagnose(claims, request(fair.networks[2])))  # other organisation
    while fair.networks[2] not in fair.started:
        await asyncio.sleep(0)
    for event in fair.release.values():
        event.set()
    await asyncio.gather(first, other)
    # Slots are released: the first organisation can run again.
    fair.release.clear()
    fair.started.clear()
    again = asyncio.create_task(fair.service().diagnose(claims, request(fair.networks[1])))
    while fair.networks[1] not in fair.started:
        await asyncio.sleep(0)
    fair.release[fair.networks[1]].set()
    assert (await again).network == fair.networks[1]


def test_live_inference_shares_per_network_admission_key():
    from app.modules.autonomy.model_diagnostic_registry import diagnostic_lock_key
    from app.modules.autonomy.model_provider import QUALIFY_LOCK

    network = uuid.uuid4()
    assert diagnostic_lock_key(network).endswith(str(network)) and str(network) not in QUALIFY_LOCK


@pytest.mark.parametrize(("configured", "expected"), [(None, 2), (1, 1), (16, 16), (0, 2), (17, 2), (True, 2), ("4", 2)])
def test_org_limit_setting_is_bounded_with_default(monkeypatch, configured, expected):
    from app.modules.autonomy.model_diagnostics import max_per_org

    settings = SimpleNamespace() if configured is None else SimpleNamespace(AUTONOMY_MODEL_DIAGNOSTICS_MAX_PER_ORG=configured)
    monkeypatch.setattr("app.core.config.get_settings", lambda: settings)
    assert max_per_org() == expected


async def test_qualification_replay_overlaps_network_inference_but_not_itself(fair, monkeypatch):
    """The installation-level replay never queues per-network work; a second replay is refused
    and the same network's diagnostic still shares the live-inference admission key."""
    import asyncio

    from app.modules.autonomy import model_provider

    gates, entered = {}, []

    async def runtime(registry, operation, **kwargs):
        key = operation if operation == "qualify" else kwargs["observation"].network_id
        entered.append(key)
        await gates.setdefault(key, asyncio.Event()).wait()
        return operation

    monkeypatch.setattr(model_provider, "confined_runtime", runtime)
    provider = model_provider.FrozenModelProvider(None, fair.redis)
    replay = asyncio.create_task(provider._runtime("qualify"))
    while "qualify" not in entered:
        await asyncio.sleep(0)
    with pytest.raises(ValueError, match="live_inference_busy"):
        await model_provider.FrozenModelProvider(None, fair.redis)._runtime("qualify")
    observation = SimpleNamespace(network_id=fair.networks[0])
    inference = asyncio.create_task(provider._runtime("infer", observation=observation, snapshot_hash="a" * 64))
    while fair.networks[0] not in entered:
        await asyncio.sleep(0)
    assert not replay.done()  # both confined runs are in flight together
    with pytest.raises(ValueError, match="live_inference_busy"):  # same network: one inference at a time
        await provider._runtime("infer", observation=observation, snapshot_hash="a" * 64)
    claims = SimpleNamespace(user_id="u")
    with pytest.raises(HTTPException) as error:
        await fair.service().diagnose(claims, request(fair.networks[0]))
    assert error.value.status_code == 429 and error.value.detail["code"] == "MODEL_DIAGNOSTIC_BUSY"
    other = asyncio.create_task(fair.service().diagnose(claims, request(fair.networks[2])))
    while fair.networks[2] not in fair.started:
        await asyncio.sleep(0)
    for event in (*gates.values(), *fair.release.values()):
        event.set()
    assert await replay == "qualify" and await inference == "infer"
    assert (await other).network == fair.networks[2]
    assert await fair.redis.keys("nanfo:autonomy:*") == []


async def test_overlapping_confined_runs_get_private_stages(monkeypatch):
    """Why the overlap is safe at the parent: each run has its own HOME/TMPDIR/cwd and stdout."""
    import asyncio
    from pathlib import Path

    from app.modules.autonomy import model_provider
    from app.modules.autonomy.live_schemas import RuntimeResult

    identity = dict(registry_sha256="1" * 64, checkpoint_sha256="2" * 64, weights_sha256="3" * 64,
                    source_sha256="4" * 64, contract_sha256="5" * 64, spec_sha256="6" * 64, report_sha256="7" * 64,
                    scope="stationary-campus-small-v4-scoped-benchmark")
    results = {"qualify": RuntimeResult(operation="qualify", **identity),
               "infer": RuntimeResult(operation="infer", **identity, snapshot_sha256="8" * 64,
                                      history_sha256="9" * 64, input_sha256="a" * 64, action=0,
                                      action_path=["access1", "dist1", "access2"], probabilities=[.9, .1],
                                      value=1., inference_seconds=.01)}
    spawned, both = [], asyncio.Event()

    class Process:
        def __init__(self, operation):
            self.returncode = None
            self.stdout, self.stderr = asyncio.StreamReader(), asyncio.StreamReader()
            self.stdout.feed_data(results[operation].model_dump_json().encode())
            self.stdout.feed_eof()
            self.stderr.feed_eof()

        async def wait(self):
            await both.wait()
            self.returncode = 0
            return 0

        def kill(self):
            self.returncode = -9

    async def spawn(*args, cwd, env, **kwargs):
        assert Path(cwd).is_dir() and env["HOME"] == env["TMPDIR"] == cwd
        spawned.append(cwd)
        if len(spawned) == 2:
            both.set()
        return Process(args[4])

    monkeypatch.setattr(model_provider.asyncio, "create_subprocess_exec", spawn)
    settings = SimpleNamespace(interpreter="/usr/bin/python3", environment=lambda: {})
    registry = SimpleNamespace(configuration=lambda: settings)
    observation = SimpleNamespace(network_id=uuid.uuid4(), workspace_id=uuid.uuid4())
    qualified, inferred = await asyncio.gather(
        model_provider.confined_runtime(registry, "qualify"),
        model_provider.confined_runtime(registry, "infer", observation=observation, snapshot_hash="8" * 64))
    assert (qualified, inferred) == (results["qualify"], results["infer"])
    first, second = map(Path, spawned)
    assert first != second and not first.is_relative_to(second) and not second.is_relative_to(first)
    assert not first.exists() and not second.exists()  # private stages are removed after each run

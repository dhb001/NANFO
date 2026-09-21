"""ADR023 providers: private fixtures, real read-only benchmark/replay, no live claim."""

import asyncio
from builtins import ExceptionGroup
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.autonomy.live_observer import LiveObserver
from app.modules.autonomy.model_provider import FrozenModelProvider, confined_runtime
from app.modules.autonomy.providers import installed_providers
from app.modules.autonomy.schemas import Qualification
from tests.live_provider_support import HISTORY, provision


@pytest.fixture
def registered(tmp_path):
    return provision(tmp_path, snapshot=True)


def redis_fixture():
    lock = MagicMock(acquire=AsyncMock(return_value=True), owned=AsyncMock(return_value=True), release=AsyncMock())
    return MagicMock(lock=MagicMock(return_value=lock), get=AsyncMock(return_value=None), set=AsyncMock())


def test_installed_selection_requires_explicit_opt_in(monkeypatch):
    for key in ("NANFO_LIVE_MODEL_REGISTRY", "NANFO_LIVE_MODEL_REGISTRY_SHA256", "NANFO_LIVE_OBSERVATION_ROOT"):
        monkeypatch.delenv(key, raising=False)
    assert installed_providers(None, None).model.inference_status.status == "unavailable"
    monkeypatch.setenv("NANFO_LIVE_MODEL_REGISTRY", "/missing")
    providers = installed_providers(None, None)
    assert isinstance(providers.observer, LiveObserver)
    assert isinstance(providers.model, FrozenModelProvider)


async def test_partial_configuration_explicit_failure(monkeypatch):
    monkeypatch.setenv("NANFO_LIVE_MODEL_REGISTRY", "/missing")
    monkeypatch.delenv("NANFO_LIVE_MODEL_REGISTRY_SHA256", raising=False)
    providers = installed_providers(None, None)
    result = await providers.model.qualify("a" * 64)
    assert not result.qualified and result.reasons == ["live_provider_configuration_incomplete"]


async def test_passive_snapshot_scope_digest_and_no_actuation(registered):
    registry, network, workspace, _ = registered
    observer = LiveObserver(registry)
    result = await observer.observe(network, workspace)
    assert result.fresh and result.compatible and result.samples == []
    assert any(value.startswith("passive_snapshot:") for value in result.evidence)
    foreign = await observer.observe(workspace, network)
    assert not foreign.fresh and not foreign.evidence
    assert foreign.reasons == ["live_observation_scope_unregistered"]


@pytest.mark.parametrize("change", ["missing_feature", "null_feature", "stale", "future", "hash", "scope", "symlink", "unprotected"])
async def test_snapshot_rejects_invalid_input(registered, change):
    registry, network, workspace, _ = registered
    from pathlib import Path
    path = Path(registry.settings.observation_root) / "snapshot.json"
    body = json.loads(path.read_bytes())
    if change == "missing_feature":
        del body["history"]["frames"][0]["response"]["data"]["observation"]["actual_offered_mbps"]
        from scripts.frozen_model_diagnostic import canonical_hash
        body["history_sha256"] = canonical_hash(body["history"])
    elif change == "null_feature":
        body["history"]["frames"][0]["response"]["data"]["observation"]["goodput_mbps"] = None
        from scripts.frozen_model_diagnostic import canonical_hash
        body["history_sha256"] = canonical_hash(body["history"])
    elif change in ("stale", "future"):
        now = datetime.now(UTC) + timedelta(seconds=-60 if change == "stale" else 60)
        body.update(observed_at=now.isoformat(), published_at=now.isoformat(),
                    window_started_at=(now - timedelta(seconds=3)).isoformat())
    elif change == "hash":
        body["history_sha256"] = "0" * 64
    elif change == "scope":
        body["network_id"] = str(workspace)
    path.write_text(json.dumps(body))
    if change == "symlink":
        target = path.with_name("other.json")
        path.rename(target)
        path.symlink_to(target)
    elif change == "unprotected":
        path.chmod(0o666)
    result = await LiveObserver(registry).observe(network, workspace)
    assert not result.compatible and not result.fresh and result.reasons


def test_registry_rejects_self_asserted_qualification_and_tampering(registered):
    registry, _, _, document = registered
    from pathlib import Path
    path = Path(registry.settings.registry_path)
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="hash_mismatch"):
        registry.load()
    from app.modules.autonomy.live_schemas import LiveInstallation
    with pytest.raises(ValueError):
        LiveInstallation.model_validate(document | {"qualified": True})


async def test_cannot_infer_with_self_asserted_qualification(registered):
    registry, network, workspace, _ = registered
    observation = await LiveObserver(registry).observe(network, workspace)
    installation = registry.load()
    qualification = Qualification(qualified=True, checkpoint_sha256=installation.model.checkpoint.sha256,
        manifest_sha256=installation.sha256, observation_contract=observation.contract, evidence=["self-assertion"])
    with pytest.raises(ValueError, match="qualification_mismatch"):
        await FrozenModelProvider(registry, redis_fixture()).infer(observation, qualification)


async def test_real_readonly_benchmark_qualification(registered):
    registry, _, _, _ = registered
    installation = registry.load()
    result = await confined_runtime(registry, "qualify")
    FrozenModelProvider._validate_result(result, installation, "qualify")
    assert result.scope == "stationary-campus-small-v4-scoped-benchmark"
    assert result.safety_authorized is False


async def test_real_historical_replay_no_live_claim(registered):
    registry, _, _, _ = registered
    from app.modules.autonomy.model_provider import RUNNER
    from app.modules.autonomy.live_schemas import RuntimeResult
    import tempfile
    env = registry.configuration().environment() | dict(OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1",
        PYTHONDONTWRITEBYTECODE="1", CUDA_VISIBLE_DEVICES="", LANG="C.UTF-8")
    with tempfile.TemporaryDirectory() as directory:
        env.update(HOME=directory, TMPDIR=directory)
        process = await asyncio.create_subprocess_exec(registry.settings.interpreter, "-I", "-B", str(RUNNER),
            "replay", "--replay-history", HISTORY, env=env, cwd=directory,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        output, errors = await asyncio.wait_for(process.communicate(), timeout=30)
        assert process.returncode == 0, errors
    result = RuntimeResult.model_validate_json(output)
    assert result.operation == "replay" and result.snapshot_sha256 is None
    assert result.action == 0 and result.value == 3.2172513008117676
    assert result.probabilities == [0.9718289375305176, 0.028171034529805183]
    assert result.input_sha256 == "ea3a62d0a12bbc608b75b49b10a294bbcaeb2ec9ce276f07965d490352c5729a"


async def test_expired_installation_is_not_qualified(registered):
    registry, _, _, _ = registered
    with pytest.raises(ValueError, match="expired"):
        registry.load(now=datetime.now(UTC) + timedelta(hours=2))


async def test_concurrent_inference_rejected(registered):
    registry, _, _, _ = registered
    redis = redis_fixture()
    redis.lock.return_value.acquire.return_value = False
    with pytest.raises(ValueError, match="busy"):
        await FrozenModelProvider(registry, redis)._runtime("qualify")
    redis.lock.return_value.release.assert_not_awaited()


async def test_qualification_pending_then_receipt_and_frozen_inference(registered, monkeypatch):
    registry, network, workspace, _ = registered
    installation = registry.load()
    redis = redis_fixture()
    cache = {}
    redis.get.side_effect = lambda key: cache.get(key)
    redis.set.side_effect = lambda key, value, **_: cache.update({key: value})
    provider = FrozenModelProvider(registry, redis)
    # Actual confined replay verifies the cached receipt path. The passive observation
    # below is a private timestamped fixture, not live qualification evidence.
    first = await provider.qualify(installation.model.checkpoint.sha256)
    assert first.reasons == ["live_qualification_pending"]
    from app.modules.autonomy.model_provider import _QUALIFICATION_TASKS
    await asyncio.gather(*list(_QUALIFICATION_TASKS))
    qualification = await provider.qualify(installation.model.checkpoint.sha256)
    assert qualification.qualified, qualification.reasons
    # Refresh fixture timestamps after the expensive historical qualification.
    from pathlib import Path
    path = Path(registry.settings.observation_root) / "snapshot.json"
    body = json.loads(path.read_bytes())
    now = datetime.now(UTC)
    body.update(observed_at=(now - timedelta(seconds=1)).isoformat(), published_at=now.isoformat(),
                window_started_at=(now - timedelta(seconds=4)).isoformat())
    path.write_text(json.dumps(body))
    observation = await LiveObserver(registry).observe(network, workspace)
    proposal = await provider.infer(observation, qualification)
    assert proposal.action_id == "route0"
    assert "execution:not_applied" in proposal.evidence
    assert "probabilities_are_safety_confidence:false" in proposal.evidence
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="hash_mismatch"):
        await provider.infer(observation, qualification)


@pytest.mark.parametrize("tamper", ["action", "checkpoint", "input", "snapshot", "contract", "scope", "stale"])
async def test_runtime_result_and_postoffload_fences(registered, monkeypatch, tamper):
    import time
    from pathlib import Path
    from app.modules.autonomy.live_schemas import MeasuredFeatures, RuntimeResult
    from scripts.frozen_model_diagnostic import canonical_hash
    registry, network, workspace, _ = registered
    installation = registry.load()
    provider = FrozenModelProvider(registry, redis_fixture())
    provider._qualified = installation.sha256, time.monotonic()
    observation = await LiveObserver(registry).observe(network, workspace)
    snapshot, digest = registry.snapshot(installation, network, workspace)
    qualification = Qualification(qualified=True, checkpoint_sha256=installation.model.checkpoint.sha256,
        manifest_sha256=installation.sha256, observation_contract=observation.contract, evidence=["private-unit-fixture"])
    result = RuntimeResult(operation="infer", registry_sha256=installation.sha256,
        checkpoint_sha256=installation.model.checkpoint.sha256, weights_sha256=installation.manifest["weights_sha256"],
        source_sha256=canonical_hash(installation.model.source_sha256), contract_sha256=installation.model.contract_sha256,
        spec_sha256=installation.model.spec_sha256, report_sha256=installation.model.report.sha256,
        scope="stationary-campus-small-v4-scoped-benchmark", snapshot_sha256=digest,
        history_sha256=snapshot.history_sha256,
        input_sha256=canonical_hash(MeasuredFeatures.model_validate(
            snapshot.history["frames"][0]["response"]["data"]["observation"]).model_dump(mode="json")),
        action=0, action_path=["access1", "dist1", "access2"], probabilities=[1., 0.], value=1., inference_seconds=.001)
    async def runtime(*args, **kwargs):
        if tamper == "stale":
            body = snapshot.model_dump(mode="json")
            now = datetime.now(UTC) - timedelta(seconds=40)
            body.update(observed_at=now.isoformat(), published_at=now.isoformat(),
                        window_started_at=(now - timedelta(seconds=3)).isoformat())
            (Path(registry.settings.observation_root) / "snapshot.json").write_text(json.dumps(body))
        return result
    if tamper == "action":
        result.action_path = ["access1", "dist2", "access2"]
    elif tamper in ("checkpoint", "input", "snapshot", "contract"):
        setattr(result, tamper + "_sha256", "0" * 64)
    elif tamper == "scope":
        observation.workspace_id = network
    monkeypatch.setattr(provider, "_runtime", runtime)
    with pytest.raises(ValueError):
        await provider.infer(observation, qualification)


@pytest.mark.parametrize("failure", ["cancel", "timeout", "output"])
async def test_confined_child_failure_is_killed_and_reaped(registered, monkeypatch, failure):
    registry, _, _, _ = registered
    from app.modules.autonomy import model_provider
    finished = asyncio.Event()
    started = asyncio.Event()
    class Process:
        returncode = None
        stdout = asyncio.StreamReader()
        stderr = asyncio.StreamReader()
        killed = False

        async def wait(self):
            started.set()
            await finished.wait()
            return self.returncode

        def kill(self):
            self.killed = True
            self.returncode = -9
            finished.set()

    process = Process()
    monkeypatch.setattr(model_provider.asyncio, "create_subprocess_exec", AsyncMock(return_value=process))
    original_timeout = asyncio.timeout
    if failure == "timeout":
        monkeypatch.setattr(model_provider.asyncio, "timeout", lambda _: original_timeout(.01))
    task = asyncio.create_task(confined_runtime(registry, "qualify"))
    await started.wait()
    if failure == "cancel":
        task.cancel()
        expected = asyncio.CancelledError
    elif failure == "output":
        process.stdout.feed_data(b"x" * (64 * 1024 + 1))
        expected = ExceptionGroup
    else:
        expected = TimeoutError
    with pytest.raises(expected):
        await task
    assert process.killed and finished.is_set()

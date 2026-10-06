"""Admission regressions at experimental trust boundaries."""

from datetime import timedelta

import pytest
from pydantic import ValidationError

from app.modules.autonomy.experimental.authority import (
    active, frame_allowed, inference_allowed, simulation_allowed, verification_allowed,
)
from app.modules.autonomy.experimental.schemas import ExperimentalPolicy, MeasuredFrame
from tests.experimental_lab_support import case


def test_complete_measured_frame_and_model_and_simulation_bindings():
    c = case()
    frame_allowed(c.policy, c.frame)
    assert inference_allowed(c.policy, c.frame, c.inference) == c.policy.routes[0]
    simulation_allowed(c.policy, c.frame, c.inference, c.simulation)
    broken = c.frame.model_dump(mode="json")
    broken["features"]["goodput_mbps"] = 99.
    with pytest.raises(ValidationError, match="features_mismatch"):
        MeasuredFrame.model_validate(broken)


@pytest.mark.parametrize("field,value", [("max_observation_age_seconds", 31), ("max_actions", 0),
    ("lease_seconds", 5), ("unknown", True)])
def test_policy_strict_bounds(field, value):
    c = case()
    with pytest.raises(ValidationError):
        ExperimentalPolicy.model_validate(c.policy.model_dump() | {field: value})


def test_stale_frame_expired_policy_changed_route_and_model_denied():
    c = case()
    stale = c.frame.model_copy(update={"snapshot": c.frame.snapshot.model_copy(
        update={"observed_at": c.frame.snapshot.observed_at - timedelta(seconds=31)})})
    with pytest.raises(ValueError, match="scope_or_age"):
        frame_allowed(c.policy, stale)
    with pytest.raises(ValueError, match="expired"):
        active(c.policy.model_copy(update={"expires_at": c.policy.starts_at}))
    with pytest.raises(ValueError, match="model_binding"):
        inference_allowed(c.policy, c.frame, c.inference.model_copy(update={"frame_sha256": "b" * 64}))
    with pytest.raises(ValueError, match="route_not_allowed"):
        inference_allowed(c.policy, c.frame, c.inference.model_copy(update={
            "proposal": c.inference.proposal.model_copy(update={"action_id": "foreign"})}))


@pytest.mark.parametrize("changes", [{"admitted": False}, {"evaluator_sha256": "b" * 64},
    {"assumptions": {"queue": "different"}}, {"policy_sha256": "b" * 64}])
def test_simulation_is_exactly_bound(changes):
    c = case()
    with pytest.raises(ValueError, match="simulation_denied"):
        simulation_allowed(c.policy, c.frame, c.inference, c.simulation.model_copy(update=changes))


async def test_unavailable_metrics_cannot_pass():
    from app.modules.autonomy.experimental.schemas import ActionCommand, utcnow
    from uuid import uuid4
    c = case()
    command = ActionCommand(request_id=uuid4(), run_id=c.policy.run_id, resource_id=c.policy.runtime.resource_id,
        fence=1, network_id=c.policy.network_id, workspace_id=c.policy.workspace_id, runtime=c.policy.runtime,
        route=c.policy.routes[0], policy_sha256="a" * 64, frame_sha256="a" * 64, inference_sha256="a" * 64,
        simulation_sha256="a" * 64, created_at=utcnow(), expires_at=c.policy.expires_at)
    prepared = await c.transport.prepare(command)
    record = await c.transport.verify(prepared)
    verification_allowed(c.policy, prepared, record)
    for key in ("goodput_mbps", "loss_fraction", "rtt_ms", "probe_sent", "probe_received", "traffic_bytes"):
        with pytest.raises(ValueError, match="unavailable"):
            verification_allowed(c.policy, prepared, record.model_copy(update={key: None}))


async def test_authority_uses_current_public_scope_contract(monkeypatch):
    from unittest.mock import AsyncMock
    from app.modules.autonomy.experimental.authority import CurrentAuthority
    c = case()
    session = AsyncMock()
    def sessions():
        return session
    authorized = AsyncMock()
    monkeypatch.setattr("app.modules.autonomy.experimental.authority.authorize", authorized)
    await CurrentAuthority(sessions, "redis").check(c.policy)
    assert authorized.call_args.kwargs == dict(db=session.__aenter__.return_value, redis="redis",
        network_id=c.policy.network_id, workspace_id=c.policy.workspace_id, actor_id=c.policy.actor_id, write=True)
    authorized.side_effect = ValueError("revoked current membership")
    with pytest.raises(ValueError, match="revoked"):
        await CurrentAuthority(sessions, "redis").check(c.policy)


async def test_protected_installation_factory_is_real_pluggable_and_hash_pinned(tmp_path, monkeypatch):
    import hashlib
    import json
    from pathlib import Path
    from types import SimpleNamespace
    from app.modules.autonomy.experimental import settings as experimental_settings
    from app.modules.autonomy.experimental.settings import load_installation
    import tests.experimental_lab_support as support
    monkeypatch.setattr(experimental_settings, "get_settings",
                        lambda: SimpleNamespace(NANFO_EXPERIMENTAL_LAB_ENABLED=True))
    c = case()
    source = Path(support.__file__)
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    config = dict(version="nanfo.experimental-installation/v1", policy=c.policy.model_dump(mode="json"),
        factory="tests.experimental_lab_support:factory", factory_sha256=source_hash,
        source_pins={str(source): source_hash}, options={})
    path = tmp_path / "installation.json"
    content = json.dumps(config).encode()
    path.write_bytes(content)
    path.chmod(0o600)
    digest = hashlib.sha256(content).hexdigest()
    installation = load_installation(str(path), digest)
    ports = await installation.build_ports()
    assert ports.transport.__class__.__name__ == "FakeTransport"
    path.write_bytes(content + b" ")
    with pytest.raises(ValueError):
        load_installation(str(path), digest)
    path.write_bytes(content)
    path.chmod(0o666)
    with pytest.raises(ValueError, match="not_protected"):
        load_installation(str(path), digest)


async def test_udp_and_icmp_loss_are_independent():
    from app.modules.autonomy.experimental.schemas import ActionCommand, utcnow
    from uuid import uuid4
    c = case()
    command = ActionCommand(request_id=uuid4(), run_id=c.policy.run_id, resource_id=c.policy.runtime.resource_id,
        fence=1, network_id=c.policy.network_id, workspace_id=c.policy.workspace_id, runtime=c.policy.runtime,
        route=c.policy.routes[0], policy_sha256="a" * 64, frame_sha256="a" * 64, inference_sha256="a" * 64,
        simulation_sha256="a" * 64, created_at=utcnow(), expires_at=c.policy.expires_at)
    prepared = await c.transport.prepare(command)
    record = await c.transport.verify(prepared)
    verification_allowed(c.policy, prepared, record.model_copy(update={"loss_fraction": .05}))
    with pytest.raises(ValueError, match="threshold_failed"):
        verification_allowed(c.policy, prepared, record.model_copy(update={"probe_received": 1}))
    with pytest.raises(ValueError, match="threshold_failed"):
        verification_allowed(c.policy, prepared, record.model_copy(update={"loss_fraction": .2}))


@pytest.mark.parametrize("kind,expected", [("fixed0", 0), ("fixed1", 1), ("heuristic", 1)])
async def test_comparators_are_honest_and_reconstructed(kind, expected):
    from app.modules.autonomy.experimental.comparators import ComparatorAdapter
    from app.modules.autonomy.experimental.schemas import InferenceRecord, Route
    c = case()
    policy = c.policy.model_copy(update={"policy_kind": kind, "routes": (
        c.policy.routes[0], Route(action_id="route1", device_ids=("router",), path=("src", "r1", "dst")))})
    record = await ComparatorAdapter(policy).infer(c.frame)
    assert record.qualification is None and record.proposal.checkpoint_sha256 is None
    assert record.result.probabilities is None and record.result.value is None
    assert record.result.action == expected
    assert inference_allowed(policy, c.frame, record) == policy.routes[expected]
    with pytest.raises(ValidationError, match="must_not_claim_model"):
        InferenceRecord.model_validate(record.model_dump() | {"qualification": c.inference.qualification})
    with pytest.raises(ValueError, match="comparator_binding"):
        inference_allowed(policy, c.frame, record.model_copy(update={
            "result": record.result.model_copy(update={"action": 1 - expected})}))


def test_true_episode_is_separate_from_journal_and_may_not_be_rewritten():
    from uuid import uuid4
    from app.modules.autonomy.experimental.schemas import contract_digest
    c = case()
    policy = c.policy.model_copy(update={"run_id": uuid4(), "measurement_run_id": c.frame.snapshot.run_id})
    frame_allowed(policy, c.frame)
    data = c.frame.model_dump(mode="json")
    data["snapshot"]["run_id"] = str(policy.run_id)
    with pytest.raises(ValidationError, match="raw_episode_mismatch"):
        MeasuredFrame.model_validate(data)
    data = c.frame.model_dump(mode="json")
    data["snapshot"]["history"]["frames"][0]["response"]["data"]["episode_id"] = str(uuid4())
    data["snapshot"]["history_sha256"] = contract_digest(data["snapshot"]["history"])
    with pytest.raises(ValidationError, match="raw_episode_mismatch"):
        MeasuredFrame.model_validate(data)


async def test_live_model_uses_true_episode_and_complete_frozen_metadata(tmp_path):
    import hashlib
    import json
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock
    from pathlib import Path
    from app.modules.autonomy.experimental import live_adapters
    from app.modules.autonomy.experimental.schemas import contract_digest
    c = case()
    digest = hashlib.sha256(Path(live_adapters.__file__).read_bytes()).hexdigest()
    equivalence = live_adapters.WrapperEquivalence(runtime=c.policy.runtime,
        registry_sha256=c.policy.registry_sha256, checkpoint_sha256=c.policy.checkpoint_sha256,
        weights_sha256=c.policy.weights_sha256, model_source_sha256=c.policy.model_source_sha256,
        model_adapter_sha256=digest, evidence_sha256=("a" * 64,), scope="fixture equivalence")
    path = tmp_path / "equivalence.json"
    content = equivalence.model_dump_json().encode()
    path.write_bytes(content)
    policy = c.policy.model_copy(update={"wrapper_equivalence_sha256": hashlib.sha256(content).hexdigest(),
                                       "model_adapter_sha256": digest})
    registry = MagicMock()
    registry.load.return_value = SimpleNamespace(sha256=policy.registry_sha256, model=SimpleNamespace(
        scopes=[SimpleNamespace(network_id=policy.network_id, workspace_id=policy.workspace_id, snapshot_path="frame.json")]))
    registry.configuration.return_value = SimpleNamespace(observation_root=str(tmp_path))
    registry.snapshot.return_value = c.frame.snapshot, contract_digest(c.frame.snapshot)
    adapter = live_adapters.LiveModelAdapter(registry, AsyncMock(), policy, equivalence_path=str(path))
    adapter.provider.qualify = AsyncMock(return_value=c.inference.qualification)
    async def infer(observation, qualification):
        assert observation.observed_at == c.frame.snapshot.observed_at
        adapter.provider.result = c.inference.result
        return c.inference.proposal
    adapter.provider.infer = infer
    record = await adapter.infer(c.frame)
    inference_allowed(policy, c.frame, record)
    saved = json.loads((tmp_path / "frame.json").read_bytes())
    assert saved["run_id"] == saved["history"]["frames"][0]["response"]["data"]["episode_id"]
    assert record.result == c.inference.result and record.model_adapter_sha256 == digest
    path.write_bytes(content + b" ")
    with pytest.raises(ValueError):
        await adapter.infer(c.frame)


async def test_review_stop_during_last_outer_authority_is_rechecked():
    """Preserve the independent review's missed-STOP interleaving as a regression."""
    from types import SimpleNamespace
    from app.modules.autonomy.experimental.controller import ExperimentalController
    from app.modules.autonomy.experimental.schemas import utcnow
    c = case()
    ctl = ExperimentalController(lambda: None, c.authority, None, c.policy)
    stopped, calls = False, 0
    async def state(**kwargs):
        if stopped:
            raise ValueError("experimental_stop_latched")
        return utcnow() + timedelta(seconds=30)
    async def authority(policy):
        nonlocal stopped, calls
        calls += 1
        if calls == 2:
            stopped = True
    ctl._checkpoint_state = state
    ctl.authority = SimpleNamespace(check=authority)
    with pytest.raises(ValueError, match="stop_latched"):
        await ctl.checkpoint()



def test_experimental_wiring_is_disabled_unless_the_setting_is_true(tmp_path, monkeypatch):
    """ADR-028: NANFO_EXPERIMENTAL_LAB_ENABLED (default False) gates the installation loader."""
    from types import SimpleNamespace
    from app.core.config import Settings
    from app.modules.autonomy.experimental import settings as experimental_settings
    from app.modules.autonomy.experimental.settings import experimental_lab_enabled, load_installation
    assert Settings.model_fields["NANFO_EXPERIMENTAL_LAB_ENABLED"].default is False
    for value in (False, None, "true", 1):
        with pytest.raises(ValueError, match="experimental_lab_disabled"):
            load_installation(str(tmp_path / "installation.json"), "a" * 64,
                              settings=SimpleNamespace(NANFO_EXPERIMENTAL_LAB_ENABLED=value))
    monkeypatch.setattr(experimental_settings, "get_settings",
                        lambda: SimpleNamespace(NANFO_EXPERIMENTAL_LAB_ENABLED=False))
    assert experimental_lab_enabled() is False
    with pytest.raises(ValueError, match="experimental_lab_disabled"):
        load_installation(str(tmp_path / "installation.json"), "a" * 64)
    enabled = SimpleNamespace(NANFO_EXPERIMENTAL_LAB_ENABLED=True)
    with pytest.raises(ValueError, match="experimental_protected_configuration_required"):
        load_installation("relative.json", "a" * 64, settings=enabled)
    # Safety operations on an already owned run never depend on the enable switch.
    for operation in ("status", "stop", "recover"):
        with pytest.raises(ValueError, match="experimental_protected_configuration_required"):
            load_installation("relative.json", "a" * 64, operation=operation)
    with pytest.raises(ValueError, match="experimental_lab_disabled"):
        load_installation("relative.json", "a" * 64, operation="run")

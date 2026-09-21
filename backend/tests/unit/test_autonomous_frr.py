"""Matching Linux action semantics and refusal/compensation with fake kernel."""

import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.modules.autonomy.frr_contract import FRRPlan
from app.modules.autonomy.frr_installation import validate_model_binding
from app.modules.autonomy.safety_provider import SafetyInstallation
from emulation.autonomous_frr import LinuxFRRDriver, RUNTIME, action_map
from tests.autonomous_execution_support import fixture
from tests.autonomous_frr_support import FakeFRRNetwork, allow_dispatch


def driver(network=None):
    return LinuxFRRDriver(network or FakeFRRNetwork(), resource_id="unit-lab", run_id="run-1",
        binding_sha256="b" * 64, ownership_check=lambda *_: True, dispatch_guard=allow_dispatch)


def plan(action=1):
    return {"runtime": RUNTIME, "action": action, "runtime_binding_sha256": "b" * 64}


@pytest.mark.parametrize("action", [0, 1])
async def test_exact_two_directional_frozen_action_map_readback_and_compensation(action):
    value = driver()
    prepared = await value.prepare(plan(action))
    assert len(prepared["resources"]) == 6
    checkpoint = AsyncMock()
    await value.apply(prepared, checkpoint)
    assert checkpoint.await_count == 12
    assert len(value.network.writes) == 12
    result = await value.verify(prepared, plan(action))
    assert result["readback_verified"] and result["probe"] == {"sent": 6, "received": 6}
    assert value.network.routePath("h2", "h4")["nodes"] == ["h2", "access1", "dist1", "access2", "h4"]
    # New driver, no in-memory mutation ownership from the previous process.
    restarted = driver(value.network)
    restored = await restarted.compensate(json.loads(json.dumps(prepared)), checkpoint)
    assert restored["restoration_verified"]
    assert not any(value.network.rules.values()) and not any(value.network.routes.values())


async def test_partial_write_timeout_restores_only_persisted_owned_resources():
    value = driver()
    prepared = await value.prepare(plan())
    value.network.fail_after = 3
    with pytest.raises(RuntimeError):
        await value.apply(prepared, AsyncMock())
    await driver(value.network).compensate(prepared, AsyncMock())
    assert len(value.network.writes) == 6


@pytest.mark.parametrize("foreign", ["selector", "nexthop", "unused_router", "extra_semantics"])
async def test_foreign_state_prevents_all_compensation_deletion(foreign):
    value = driver()
    prepared = await value.prepare(plan())
    await value.apply(prepared, AsyncMock())
    if foreign == "selector":
        value.network.rules[("access1", 19110)][0]["src"] = "192.0.2.1/32"
    elif foreign == "nexthop":
        value.network.routes[("access1", 19110)][0]["gateway"] = "192.0.2.1"
    elif foreign == "unused_router":
        value.network.rules[("core", 19110)] = [{"priority": 19110, "table": 19110}]
    else:
        value.network.rules[("access1", 19110)][0]["fwmark"] = "0x1"
    before = len(value.network.writes)
    with pytest.raises(ValueError, match="foreign"):
        await value.compensate(prepared, AsyncMock())
    assert len(value.network.writes) == before


async def test_receiver_checkpoint_denies_second_kernel_write():
    value = driver()
    prepared = await value.prepare(plan())
    checkpoint = AsyncMock(side_effect=[None, ValueError("revoked")])
    with pytest.raises(ValueError, match="revoked"):
        await value.apply(prepared, checkpoint)
    assert len(value.network.writes) == 1
    await value.compensate(prepared, AsyncMock())


def test_versioned_plan_and_installation_require_independent_runtime_reference():
    data = fixture().installation.data.model_dump(mode="json")
    data["runtime_action"] = RUNTIME
    for index, action in enumerate(data["actions"]):
        action["plan"] = plan(index)
    with pytest.raises(ValidationError, match="runtime_evidence_required"):
        SafetyInstallation.model_validate(data)
    data["runtime_binding"] = {"path": "runtime.json", "sha256": "b" * 64, "size_bytes": 100}
    parsed = SafetyInstallation.model_validate(data)
    assert isinstance(parsed.actions[0].plan, FRRPlan)
    data["actions"][0]["plan"]["manual_approval"] = True
    with pytest.raises(ValidationError):
        SafetyInstallation.model_validate(data)


def test_model_fingerprint_contract_stays_exact_no_loader_translation():
    binding = SimpleNamespace(checkpoint_sha256="a" * 64, model_contract_sha256="b" * 64,
        model_spec_sha256="c" * 64, actions=action_map(), action_ids=["path0", "path1"],
        frozen_sources={"emulation/matched.py": "e" * 64})
    installation = SimpleNamespace(model=SimpleNamespace(runtime_action="linux-frr-host-route",
        checkpoint=SimpleNamespace(sha256="a" * 64), contract_sha256="b" * 64, spec_sha256="c" * 64,
        action_ids=["path0", "path1"]), manifest={"contract": {"action_map": list(action_map().values())},
            "environment_spec": {"version": 4, "source_files": {"matched.py": "e" * 64}}})
    validate_model_binding(binding, installation)
    changed = copy.deepcopy(installation)
    changed.model.spec_sha256 = "d" * 64
    with pytest.raises(ValueError, match="identity_mismatch"):
        validate_model_binding(binding, changed)


async def test_compensation_is_not_gated_by_expired_model_guard():
    value = driver()
    prepared = await value.prepare(plan())
    await value.apply(prepared, AsyncMock())
    value.dispatch_guard = AsyncMock(side_effect=ValueError("expired_model"))
    await value.compensate(prepared, AsyncMock())
    value.dispatch_guard.assert_not_called()


def test_independent_runtime_binding_requires_pins_exact_scope_and_actual_sources(tmp_path):
    import hashlib
    import time
    from app.modules.autonomy.artifact_io import ArtifactStore
    from app.modules.autonomy.frr_installation import (
        FROZEN_SOURCES, RECEIVER_SOURCES, runtime_sources, validate_runtime_binding,
    )
    from pathlib import Path
    from tests.autonomous_execution_support import fixture

    data = fixture(runtime="frr").installation.data
    root = Path(__file__).parents[3]
    sources = runtime_sources(root)
    equivalence = b"unit-only-reviewed-equivalence-fixture-not-runtime-qualification"
    digest = hashlib.sha256(equivalence).hexdigest()
    (tmp_path / "equivalence.txt").write_bytes(equivalence)
    binding = dict(version="nanfo.autonomous-frr-runtime/v1", runtime=RUNTIME,
        network_id=str(data.network_id), workspace_id=str(data.workspace_id), run_id=data.calibration.run_id,
        resource_id="unit-lab", provider_id=data.calibration.provider_id, configuration_sha256=data.configuration_sha256,
        checkpoint_sha256=data.checkpoints[0], model_contract_sha256="c" * 64, model_spec_sha256="d" * 64,
        qualified_image_id="sha256:" + "e" * 64, receiver_image_id="sha256:" + "f" * 64,
        frozen_sources={p: sources[p] for p in FROZEN_SOURCES}, receiver_sources={p: sources[p] for p in RECEIVER_SOURCES},
        actions=action_map(), action_ids=["baseline", "test-action"], baseline_action=0,
        namespaces={n: dict(pid=100 + i, start_ticks=1, netns_inode=200 + i)
                    for i, n in enumerate(["access1", "access2", "dist1", "dist2", "core", "h1", "h2", "h3", "h4"])},
        reviewed_equivalence=dict(path="equivalence.txt", sha256=digest, size_bytes=len(equivalence)),
        valid_from=time.time() - 10, valid_until=time.time() + 200)
    content = json.dumps(binding).encode()
    pin = hashlib.sha256(content).hexdigest()
    data.runtime_binding = data.runtime_binding.model_copy(update={"sha256": pin, "size_bytes": len(content)})
    for a in data.actions:
        a.plan.runtime_binding_sha256 = pin
    kwargs = dict(accepted_runtime_sha256={pin}, accepted_equivalence_sha256={digest},
                  store=ArtifactStore(str(tmp_path)), source_root=root)
    assert validate_runtime_binding(data, {data.runtime_binding.path: content}, **kwargs).runtime == RUNTIME
    with pytest.raises(ValueError, match="not_independently_accepted"):
        validate_runtime_binding(data, {data.runtime_binding.path: content}, **{**kwargs, "accepted_runtime_sha256": set()})
    binding["receiver_sources"]["emulation/autonomous_frr.py"] = "0" * 64
    changed = json.dumps(binding).encode()
    changed_pin = hashlib.sha256(changed).hexdigest()
    data.runtime_binding = data.runtime_binding.model_copy(update={"sha256": changed_pin})
    with pytest.raises(ValueError, match="fingerprint_mismatch"):
        validate_runtime_binding(data, {data.runtime_binding.path: changed},
                                 **{**kwargs, "accepted_runtime_sha256": {changed_pin}})

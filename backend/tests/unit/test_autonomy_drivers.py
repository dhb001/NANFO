"""ADR-028 fix 7: capability-driven runtime/driver registry; no brand logic in core modules."""

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.modules.autonomy.drivers import (
    Capability,
    RuntimeProfile,
    bind_driver,
    driver_capabilities,
    register_runtime,
    runtime_profile,
)
from app.modules.autonomy.execution import AutonomousExecutor
from app.modules.autonomy.safety_provider import ValidatedInstallation
from tests.autonomous_execution_support import FakeDevice, fixture

BACKEND = Path(__file__).resolve().parents[2]
CORE = ["execution.py", "execution_authority.py", "execution_client.py", "execution_composition.py",
        "execution_repository.py", "safety_installation.py", "safety_provider.py", "service.py", "worker.py",
        "providers.py", "repository.py", "overrides.py", "receiver_health.py", "execution_settings.py"]
BRANDS = ("isolated-linux-frr-host-route", "isolated-ovs-autonomous", "linux-frr-host-route", "IsolatedOVSDriver",
          "LinuxFRRDriver", "emulation.actions", "emulation.autonomous_driver")


def test_builtin_profiles_declare_capabilities():
    ovs = runtime_profile("isolated-ovs-autonomous/v1")
    frr = runtime_profile("isolated-linux-frr-host-route/v1")
    assert ovs.requires == frozenset() and ovs.plan_binding_fields == frozenset()
    assert frr.requires == {Capability.INDEPENDENT_DISPATCH_GUARD, Capability.RUNTIME_BINDING}
    assert frr.plan_binding_fields == {"runtime_binding_sha256"} and frr.validate_runtime_binding is not None
    assert ovs.lab_driver_factory is not None and frr.lab_driver_factory is None


def test_unknown_runtime_fails_closed():
    with pytest.raises(ValueError, match="unregistered"):
        runtime_profile("vendor-x/v9")


def test_conflicting_registration_rejected():
    profile = runtime_profile("isolated-ovs-autonomous/v1")
    assert register_runtime(profile) is profile
    with pytest.raises(ValueError, match="conflict"):
        register_runtime(RuntimeProfile(runtime_id=profile.runtime_id, plan_type=dict))


@pytest.mark.parametrize("driver,expected", [
    (SimpleNamespace(), frozenset()),
    (SimpleNamespace(dispatch_guard=AsyncMock()), frozenset({Capability.INDEPENDENT_DISPATCH_GUARD})),
    (SimpleNamespace(dispatch_guard="not callable"), frozenset()),
    (SimpleNamespace(capabilities=["independent_dispatch_guard"]), frozenset({Capability.INDEPENDENT_DISPATCH_GUARD})),
    (SimpleNamespace(capabilities=[], dispatch_guard=AsyncMock()), frozenset()),
])
def test_driver_capabilities_are_declared_or_detected(driver, expected):
    assert driver_capabilities(driver) == expected


def test_executor_binds_driver_through_required_capabilities():
    case = fixture()
    executor = AutonomousExecutor(None, None, case.installation, FakeDevice(), "unit-lab")
    assert executor.authority.runtime_guard is None
    frr = fixture(runtime="frr")
    device = FakeDevice()
    device.driver_id = frr.installation.data.runtime_action
    with pytest.raises(ValueError, match="driver_capability_missing:independent_dispatch_guard"):
        AutonomousExecutor(None, None, frr.installation, device, "unit-lab")
    device.dispatch_guard = AsyncMock()
    executor = AutonomousExecutor(None, None, frr.installation, device, "unit-lab")
    assert executor.authority.runtime_guard is device.dispatch_guard
    with pytest.raises(ValueError, match="installed_lab_driver_scope_mismatch"):
        AutonomousExecutor(None, None, case.installation, device, "unit-lab")  # FRR driver for an OVS install


def test_bind_driver_rejects_driver_for_other_runtime():
    case = fixture()
    with pytest.raises(ValueError, match="installed_lab_driver_scope_mismatch"):
        bind_driver(SimpleNamespace(driver_id="vendor-x/v9"), case.installation.data)


def test_installation_validation_uses_profile_plan_binding():
    import json

    frr = fixture(runtime="frr")
    data = json.loads(frr.installation.content)
    data["actions"][0]["plan"]["runtime_binding_sha256"] = "c" * 64
    content = json.dumps(data).encode()
    with pytest.raises(ValueError, match="runtime_evidence_required"):
        ValidatedInstallation(content, "d" * 64).data
    data = json.loads(fixture().installation.content)
    data["runtime_binding"] = {"path": "unit-runtime.json", "sha256": "b" * 64, "size_bytes": 1}
    with pytest.raises(ValueError, match="runtime_binding_not_supported"):
        ValidatedInstallation(json.dumps(data).encode(), "d" * 64).data


async def test_accept_under_worker_lock_skips_runtime_guard(monkeypatch):
    frr = fixture(runtime="frr")
    device = FakeDevice()
    device.driver_id, device.dispatch_guard = frr.installation.data.runtime_action, AsyncMock()
    executor = AutonomousExecutor(None, None, frr.installation, device, "unit-lab")
    calls = []
    async def check(db, authorization, *, accepted=False, runtime_guard=True):
        calls.append(runtime_guard)
    monkeypatch.setattr(executor.authority, "check", check)
    monkeypatch.setattr("app.modules.autonomy.execution_repository.ExecutionRepository.stage", AsyncMock())
    await executor.accept(SimpleNamespace(), frr.auth)
    assert calls == [False, False]
    device.dispatch_guard.assert_not_awaited()


@pytest.mark.parametrize("name", CORE)
def test_core_modules_have_no_runtime_brand_logic(name):
    import re

    source = (BACKEND / "app/modules/autonomy" / name).read_text()
    # Versioned wire contracts may enumerate accepted runtime ids; logic may not.
    logic = re.sub(r"Literal\[[^\]]*\]", "Literal[...]", source)
    assert not any(brand in logic for brand in BRANDS), name
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Compare):
            names = {getattr(side, "attr", None) for side in (node.left, *node.comparators)}
            assert "driver_id" not in names, f"{name}: driver_id comparison"


def test_emulation_is_not_imported_by_core_modules():
    for name in CORE:
        tree = ast.parse((BACKEND / "app/modules/autonomy" / name).read_text())
        for node in tree.body:  # module level only; lab code may be imported lazily in functions
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = node.module if isinstance(node, ast.ImportFrom) else node.names[0].name
                assert not (module or "").startswith("emulation"), f"{name} imports {module} at import time"


def test_receiver_fingerprint_covers_new_receiver_path_modules():
    from app.modules.autonomy.frr_installation import RECEIVER_SOURCES

    for path in ("backend/app/modules/autonomy/drivers.py", "backend/app/modules/autonomy/ovs_runtime.py",
                 "backend/app/modules/autonomy/confidence.py", "backend/app/core/canonical.py"):
        assert path in RECEIVER_SOURCES and (BACKEND.parent / path).is_file()

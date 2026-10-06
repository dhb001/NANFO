"""ADR-028: measured detector caches binding/pre-lock authority, fences commits once."""

import uuid
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import app.modules.alert.measured as measured
from app.modules.alert.detector import DetectorSettings
from app.modules.alert.measured import MeasuredAlertService
from app.modules.network.emulation import EmulationBinding
from tests.alert_support import ACTOR, DEVICE, NETWORK, ORG, WORKSPACE, observation

REVISION = ("/fixture/binding", "/fixture/snapshot", 1, 2, 3, 4, 5)
BINDING = EmulationBinding(version=1, topology_id="campus-small-v1", network_id=NETWORK, workspace_id=WORKSPACE,
                           actor_user_id=ACTOR, switches={"0000000000000001": DEVICE}, hosts={},
                           port_capacities_mbps={"0000000000000001:1": 100.0})


@pytest.fixture(autouse=True)
def isolated_caches(monkeypatch):
    measured.clear_authority_caches()
    monkeypatch.setattr(measured, "get_settings", lambda: SimpleNamespace(
        EXECUTION_MODE="emulation", EMULATION_BINDING_PATH="/fixture/binding",
        EMULATION_SNAPSHOT_PATH="/fixture/snapshot"))
    yield
    measured.clear_authority_caches()


async def test_binding_is_cached_per_revision_and_reloaded_when_the_file_changes(monkeypatch):
    revision = [REVISION]
    loader = AsyncMock(return_value=BINDING)
    monkeypatch.setattr(measured, "load_binding", loader)
    monkeypatch.setattr(measured, "_binding_revision", lambda path, snapshot: revision[0])
    for _ in range(3):
        assert await measured._cached_binding(measured.Path("/b"), measured.Path("/s")) == (BINDING, REVISION)
    assert loader.await_count == 1
    revision[0] = (*REVISION[:-1], 6)  # ctime changed: new revision
    await measured._cached_binding(measured.Path("/b"), measured.Path("/s"))
    assert loader.await_count == 2
    monkeypatch.setattr(measured, "BINDING_CACHE_SECONDS", -1)  # TTL elapsed
    await measured._cached_binding(measured.Path("/b"), measured.Path("/s"))
    assert loader.await_count == 3


async def test_unobservable_binding_file_is_never_cached(monkeypatch):
    loader = AsyncMock(return_value=BINDING)
    monkeypatch.setattr(measured, "load_binding", loader)
    monkeypatch.setattr(measured, "_binding_revision", lambda path, snapshot: None)
    for _ in range(2):
        assert await measured._cached_binding(measured.Path("/b"), measured.Path("/s")) == (BINDING, None)
    assert loader.await_count == 2


async def test_pre_lock_authority_is_cached_but_fence_authorization_is_always_fresh(mock_db, monkeypatch):
    loader = AsyncMock(return_value=BINDING)
    monkeypatch.setattr(measured, "load_binding", loader)
    monkeypatch.setattr(measured, "_binding_revision", lambda path, snapshot: REVISION)
    authority = AsyncMock(return_value=ORG)
    monkeypatch.setattr(MeasuredAlertService, "_current_authority", authority)

    class Session:
        def __init__(self, **kwargs):
            self.bind = kwargs.get("bind")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(measured, "AsyncSession", Session)
    service, sample = MeasuredAlertService(db=mock_db), observation()
    for _ in range(3):
        assert await service.authorize_observation(sample) == ORG
    assert authority.await_count == 1  # reads binding files/devices once, not per sample
    assert await service.authorize_observation(sample, fresh=True) == ORG
    assert await service.authorize_observation(sample, fresh=True) == ORG
    assert authority.await_count == 3  # fences never trust the cache
    assert loader.await_count == 1  # the binding itself is reused per revision
    monkeypatch.setattr(measured, "AUTHORITY_CACHE_SECONDS", -1)
    await service.authorize_observation(sample)
    assert authority.await_count == 4


async def test_binding_scope_is_checked_before_any_cached_authority(mock_db, monkeypatch):
    monkeypatch.setattr(measured, "load_binding", AsyncMock(return_value=BINDING))
    monkeypatch.setattr(measured, "_binding_revision", lambda path, snapshot: REVISION)
    monkeypatch.setattr(MeasuredAlertService, "_current_authority", AsyncMock(return_value=ORG))
    service = MeasuredAlertService(db=mock_db)
    await service.authorize_observation(observation())
    with pytest.raises(ValueError, match="binding scope"):
        await service.authorize_observation(observation(workspace_id=uuid.uuid4()))


def _prepared_service(mock_db, monkeypatch, *, accepted=True, clock=None):
    sample = observation()
    rule = DetectorSettings().utilization
    service = MeasuredAlertService(db=mock_db, clock=clock or (lambda: sample.observed_at))
    service.repo.lock_detector = AsyncMock(return_value=SimpleNamespace(
        rule=rule.model_dump(), incident_id=None, last_observed_at=None, last_event_id=None,
        phase=None, phase_since=None, sample_count=0))
    service.repo.accept_observation = AsyncMock(return_value=accepted)
    evidence = SimpleNamespace(event_reference=AsyncMock(return_value=object()), pin=AsyncMock())
    monkeypatch.setattr(measured, "TelemetryEvidenceService", lambda db, scope: evidence)
    service.authorize_observation = AsyncMock(return_value=ORG)
    return service, sample


@pytest.mark.parametrize("accepted", [True, False])
async def test_apply_authorizes_exactly_once_immediately_before_commit(mock_db, monkeypatch, accepted):
    # Regression: three full authorizations (binding file + device paging) per sample.
    service, sample = _prepared_service(mock_db, monkeypatch, accepted=accepted)
    await service.apply_observation(sample, ORG)
    service.authorize_observation.assert_awaited_once_with(sample, fresh=True)
    mock_db.commit.assert_awaited_once()
    mock_db.rollback.assert_not_awaited()


@pytest.mark.parametrize("fault", ["revoked", "other_org"])
async def test_fence_failure_rolls_back_everything(mock_db, monkeypatch, fault):
    service, sample = _prepared_service(mock_db, monkeypatch)
    if fault == "revoked":
        service.authorize_observation.side_effect = ValueError("observer capability revoked")
    else:
        service.authorize_observation.return_value = uuid.uuid4()
    await service.apply_observation(sample, ORG)
    mock_db.rollback.assert_awaited_once()
    mock_db.commit.assert_not_awaited()


async def test_expiry_while_waiting_for_locks_rolls_back_without_authority_io(mock_db, monkeypatch):
    sample = observation()
    times = iter([sample.observed_at, sample.observed_at + timedelta(seconds=31)])
    service, _ = _prepared_service(mock_db, monkeypatch, clock=lambda: next(times))
    await service.apply_observation(sample, ORG)
    service.authorize_observation.assert_not_awaited()
    service.repo.accept_observation.assert_not_awaited()
    mock_db.rollback.assert_awaited_once()
    mock_db.commit.assert_not_awaited()

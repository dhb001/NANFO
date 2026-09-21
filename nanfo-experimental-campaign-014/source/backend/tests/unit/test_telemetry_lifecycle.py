"""Cursor integrity and conservative owner-contract lifecycle behavior."""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.modules.telemetry.cursor import CursorState, HistoryCursorCodec, TelemetryCursorService
from app.modules.telemetry.pins import (
    REQUIRED_EVIDENCE_OWNERS,
    EvidenceOwnerScope,
    EvidenceReference,
    ProspectiveCoverageContract,
    TelemetryEvidenceService,
)
from app.modules.telemetry.retention import ArchivalAssessmentRequest, TelemetryRetentionService
from app.modules.telemetry.schemas import TelemetryCursorRequest, TelemetryHistoryQuery

NOW = datetime(2026, 9, 20, tzinfo=UTC)
WORKSPACE, NETWORK, ACTOR = uuid.UUID(int=1), uuid.UUID(int=2), uuid.UUID(int=3)


def record(number):
    return SimpleNamespace(
        record_id=uuid.UUID(int=number), event_id=uuid.uuid4(), correlation_id=uuid.uuid4(),
        device_id=uuid.uuid4(), network_id=NETWORK, workspace_id=WORKSPACE, metric="cpu",
        value=1, unit="percent", observed_at=NOW, source="fixture", tags={}, created_at=NOW,
    )


def test_codec_tamper_expiry_domain_and_bounds():
    codec = HistoryCursorCodec("test-only-secret")
    state = CursorState(
        scope="a" * 64, cutoff=NOW, expires=NOW + timedelta(minutes=15),
        upper_at=NOW, upper_id=uuid.UUID(int=9), last_at=NOW, last_id=uuid.UUID(int=8),
    )
    token = codec.encode(state)
    assert codec.decode(token, scope=state.scope, now=NOW) == state
    for invalid in ["", "x.y", token + "=", token + ".extra", "x" * 4097,
                    token[0:5] + ("A" if token[5] != "A" else "B") + token[6:]]:
        with pytest.raises(HTTPException) as exc:
            codec.decode(invalid, scope=state.scope, now=NOW)
        assert exc.value.status_code == 400
    for other_codec, scope, now, other_token in [
        (HistoryCursorCodec("rotated-secret"), state.scope, NOW, token),
        (codec, "b" * 64, NOW, token),
        (codec, state.scope, state.expires, token),
        (codec, state.scope, NOW - timedelta(seconds=1), token),
        (codec, state.scope, NOW, codec.encode(state.model_copy(update={"last_id": uuid.UUID(int=10)}))),
        (codec, state.scope, NOW, codec.encode(state.model_copy(update={"expires": NOW + timedelta(days=1)}))),
    ]:
        with pytest.raises(HTTPException):
            other_codec.decode(other_token, scope=scope, now=now)


@pytest.mark.parametrize("change", [
    {"actor_id": uuid.UUID(int=4)}, {"workspace_id": uuid.UUID(int=4)},
    {"network_id": None}, {"network_id": uuid.UUID(int=4)}, {"page_size": 2},
    {"query": TelemetryHistoryQuery(metric="memory")},
    {"query": TelemetryHistoryQuery(metric="cpu", start_time=NOW)},
    {"query": TelemetryHistoryQuery(metric="cpu", end_time=NOW)},
])
async def test_cursor_replay_binds_all_scope_and_filter_fields(change):
    service = TelemetryCursorService(AsyncMock())
    service._repo = AsyncMock()
    service._repo.list_history_keyset.return_value = [record(9), record(8)]
    params = dict(actor_id=ACTOR, workspace_id=WORKSPACE, network_id=NETWORK,
                  query=TelemetryHistoryQuery(metric="cpu"), page_size=1, cursor=None)
    first = await service.get_history(**params)
    assert first.next_cursor and first.upper_record_id == uuid.UUID(int=9)
    service._repo.reset_mock()
    with pytest.raises(HTTPException) as exc:
        await service.get_history(**{**params, "cursor": first.next_cursor, **change})
    assert exc.value.status_code == 400
    service._repo.list_history_keyset.assert_not_awaited()


async def test_cursor_preserves_upper_and_cutoff_without_renewing():
    service = TelemetryCursorService(AsyncMock())
    service._repo = AsyncMock()
    service._repo.list_history_keyset.side_effect = [[record(9), record(8)], [record(8), record(7)], []]
    params = dict(actor_id=ACTOR, workspace_id=WORKSPACE, network_id=NETWORK,
                  query=TelemetryHistoryQuery(), page_size=1)
    first = await service.get_history(**params, cursor=None)
    second = await service.get_history(**params, cursor=first.next_cursor)
    third = await service.get_history(**params, cursor=second.next_cursor)
    calls = service._repo.list_history_keyset.call_args_list
    assert calls[0].kwargs["cutoff"] == calls[1].kwargs["cutoff"] == calls[2].kwargs["cutoff"]
    assert calls[1].kwargs["after"] == (NOW, uuid.UUID(int=9))
    assert calls[2].kwargs["after"] == (NOW, uuid.UUID(int=8))
    assert second.upper_record_id == third.upper_record_id == first.upper_record_id
    assert third.items == [] and third.next_cursor is None


@pytest.mark.parametrize("params", [
    {"cursor": "token"}, {"pagination": "cursor", "page": 2},
    {"pagination": "cursor", "aggregation": "avg"},
    {"pagination": "cursor", "bucket_seconds": 1}, {"page_size": 201},
])
def test_cursor_modes_reject_ambiguous_requests(params):
    with pytest.raises(ValidationError):
        TelemetryCursorRequest(**params)


def coverage(owner, **overrides):
    return SimpleNamespace(**{ "owner": owner, "version": 1, "contract": "pin-before-reference/v1",
                              "registered_at": NOW, "revoked_at": None, **overrides})


def candidate(number, **overrides):
    return SimpleNamespace(**{"record_id": uuid.UUID(int=number), "created_at": NOW,
                              "observed_at": NOW, "pinned": False, **overrides})


@pytest.mark.parametrize("registrations", [[], [coverage("report")],
    [coverage(owner, revoked_at=NOW if owner == "intent" else None) for owner in REQUIRED_EVIDENCE_OWNERS],
    [coverage(owner, version=2 if owner == "report" else 1) for owner in REQUIRED_EVIDENCE_OWNERS],
    [coverage(owner) for owner in REQUIRED_EVIDENCE_OWNERS] + [coverage("unknown")],
])
async def test_unknown_partial_revoked_coverage_fails_closed(registrations):
    service = TelemetryRetentionService(AsyncMock())
    service._repo = AsyncMock()
    service._repo.coverage.return_value = registrations
    service._repo.assessment_batch.return_value = [candidate(1), candidate(2, pinned=True)]
    result = await service.assess(ArchivalAssessmentRequest(
        workspace_id=WORKSPACE, start_time=NOW, end_time=NOW + timedelta(days=1),
    ))
    assert result.coverage_unknown == [uuid.UUID(int=1)]
    assert result.pinned == [uuid.UUID(int=2)]
    assert result.prospective_candidates == [] and result.prospective_since is None
    assert result.dry_run and result.deleted == 0


async def test_prospective_coverage_never_certifies_history_and_batches_are_bounded():
    service = TelemetryRetentionService(AsyncMock())
    service._repo = AsyncMock()
    service._repo.coverage.return_value = [coverage(owner) for owner in REQUIRED_EVIDENCE_OWNERS]
    service._repo.assessment_batch.return_value = [
        candidate(1, observed_at=NOW - timedelta(seconds=1)),
        candidate(2, created_at=NOW - timedelta(seconds=1)),
        candidate(3, pinned=True), candidate(4), candidate(5),
    ]
    result = await service.assess(ArchivalAssessmentRequest(
        workspace_id=WORKSPACE, start_time=NOW - timedelta(days=1),
        end_time=NOW + timedelta(days=1), batch_size=4,
    ))
    assert result.coverage_unknown == [uuid.UUID(int=1), uuid.UUID(int=2)]
    assert result.pinned == [uuid.UUID(int=3)]
    assert result.prospective_candidates == [uuid.UUID(int=4)]
    assert result.next_position.record_id == uuid.UUID(int=4)


async def test_owner_registration_and_pin_contract_are_explicit_and_scoped():
    from app.modules.telemetry.reconciliation import owner_contracts

    owner_contracts()
    service = TelemetryEvidenceService(AsyncMock(), scope=EvidenceOwnerScope(owner="report", workspace_id=WORKSPACE))
    service._repo = AsyncMock()
    service._repo.register.return_value = coverage("report")
    with pytest.raises(ValidationError):
        await service.register_prospective({"version": 1})
    service._repo.register.assert_not_awaited()
    contract = ProspectiveCoverageContract(version=1, contract="pin-before-reference/v1")
    service._repo.reconciled.return_value = False
    with pytest.raises(ValueError, match="reconciliation"):
        await service.register_prospective(contract)
    service._repo.reconciled.return_value = True
    await service.register_prospective(contract)
    service._repo.register.assert_awaited_once_with(owner="report", workspace_id=WORKSPACE)
    service._repo.register.return_value = coverage("report", revoked_at=NOW)
    with pytest.raises(ValueError, match="cannot reactivate"):
        await service.register_prospective(contract)
    reference = EvidenceReference(network_id=NETWORK, reference_id=uuid.uuid4(), record_id=uuid.uuid4())
    service._repo.pin.return_value = SimpleNamespace(released_at=None)
    await service.pin(reference)
    service._repo.pin.assert_awaited_once_with(owner="report", workspace_id=WORKSPACE, **reference.model_dump())
    service._repo.pin.return_value = SimpleNamespace(released_at=NOW)
    with pytest.raises(ValueError, match="cannot be reused"):
        await service.pin(reference)
    await service.release(reference)
    service._repo.release.assert_awaited_once_with(owner="report", workspace_id=WORKSPACE, **reference.model_dump())


@pytest.mark.parametrize("overrides", [
    {"start_time": NOW.replace(tzinfo=None)}, {"end_time": NOW},
    {"end_time": NOW + timedelta(days=32)}, {"batch_size": 1001},
    {"after": {"observed_at": NOW - timedelta(seconds=1), "record_id": uuid.uuid4()}},
])
def test_assessment_input_bounds(overrides):
    with pytest.raises(ValidationError):
        ArchivalAssessmentRequest(**{ "workspace_id": WORKSPACE, "start_time": NOW,
                                      "end_time": NOW + timedelta(days=1), **overrides})

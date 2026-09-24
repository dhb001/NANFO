"""Unit tests for alert service lifecycle and ingestion behavior."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.modules.alert.scope import AlertListScope
from app.modules.alert.service import AlertService

WORKSPACE, ORG, OTHER_WORKSPACE = uuid.UUID(int=501), uuid.UUID(int=502), uuid.UUID(int=503)
NETWORKS = [uuid.UUID(int=600 + i) for i in range(2)]


@pytest.fixture(autouse=True)
def isolated_history_repository(monkeypatch):
    monkeypatch.setattr("app.modules.alert.repository.AlertRepository.append_history", AsyncMock(return_value=uuid.uuid4()))
    monkeypatch.setattr("app.modules.alert.repository.AlertRepository.consume_generation", AsyncMock(return_value=True))
    monkeypatch.setattr("app.modules.alert.repository.AlertRepository.link_consumed_generation", AsyncMock())
    monkeypatch.setattr("app.modules.alert.repository.AlertRepository.lock_legacy_identity", AsyncMock())


def _make_alert_row(
    *,
    alert_id: uuid.UUID | None = None,
    alert_key: str = "telemetry_runtime_adapter_slo_threshold_breach",
    status: str = "active",
    severity: str | None = "critical",
    scope: dict | None = None,
) -> SimpleNamespace:
    now = datetime.now(UTC)
    row_alert_id = alert_id or uuid.uuid4()
    return SimpleNamespace(
        alert_id=row_alert_id,
        alert_key=alert_key,
        source="telemetry",
        status=status,
        severity=severity,
        correlation_id=uuid.uuid4(),
        payload={
            "alert_id": str(row_alert_id),
            "alert_key": alert_key,
            "status": status,
            "severity": severity,
            **(scope or {}),
        },
        acknowledged_by_user_id=None,
        resolved_by_user_id=None,
        acknowledged_at=None,
        resolved_at=None,
        created_at=now,
        updated_at=now,
    )


def _scoped_list_service(mock_db, fake_redis, rows, counts):
    service = AlertService(db=mock_db, redis=fake_redis)
    service._assert_alert_access = AsyncMock(side_effect=AssertionError("list must not authorize per row"))
    service._accessible_scopes = AsyncMock(return_value=AlertListScope(workspace_orgs={WORKSPACE: ORG}))
    service._workspace_svc.list_accessible_workspace_ids = AsyncMock(return_value=[WORKSPACE])
    service._network_svc.list_networks = AsyncMock(return_value=SimpleNamespace(
        items=[SimpleNamespace(network_id=network) for network in NETWORKS], total=len(NETWORKS)))
    service._repo.list_alerts = AsyncMock(return_value=rows)
    service._repo.count_alerts = AsyncMock(return_value=counts)
    return service


@pytest.mark.asyncio
async def test_list_alerts_normalizes_filters_and_returns_status_counts(mock_db, fake_redis):
    scope = {"workspace_id": str(WORKSPACE)}
    service = _scoped_list_service(mock_db, fake_redis, [
        _make_alert_row(status="active", scope=scope),
        _make_alert_row(status="ACKNOWLEDGED", scope=scope),
        _make_alert_row(status="resolved", scope=scope),
    ], {"active": 1, "ACKNOWLEDGED": 1, "resolved": 1})

    result = await service.list_alerts(
        status_filter="ACTIVE",
        severity_filter="CRITICAL",
        source_filter="Telemetry",
        correlation_id_filter=uuid.uuid4(),
        search_filter="  link down  ",
        limit=999,
        actor_user_id=str(uuid.uuid4()),
        requested_workspace_id=WORKSPACE,
        claim_org_id=ORG,
    )

    assert result.total == 3
    assert result.status_counts["active"] == 1
    assert result.status_counts["acknowledged"] == 1
    assert result.status_counts["resolved"] == 1
    for call in (service._repo.list_alerts, service._repo.count_alerts):
        assert call.await_args.kwargs["status"] == "active"
        assert call.await_args.kwargs["severity"] == "critical"
        assert call.await_args.kwargs["source"] == "telemetry"
        assert call.await_args.kwargs["search"] == "link down"
    assert service._repo.list_alerts.await_args.kwargs["limit"] == 500
    service._assert_alert_access.assert_not_awaited()


@pytest.mark.asyncio
async def test_list_alerts_filters_out_forbidden_alert_rows(mock_db, fake_redis):
    allowed_row = _make_alert_row(status="active", scope={"workspace_id": str(WORKSPACE)})
    denied_row = _make_alert_row(status="resolved", scope={"workspace_id": str(OTHER_WORKSPACE)})
    unscoped_row = _make_alert_row(status="resolved")
    service = _scoped_list_service(mock_db, fake_redis, [allowed_row, denied_row, unscoped_row],
                                   {"active": 1, "resolved": 2})

    result = await service.list_alerts(
        status_filter=None,
        severity_filter=None,
        source_filter=None,
        correlation_id_filter=None,
        search_filter=None,
        limit=50,
        actor_user_id=str(uuid.uuid4()),
        requested_workspace_id=WORKSPACE,
        claim_org_id=ORG,
    )

    assert result.total == 1
    assert len(result.items) == 1
    assert result.items[0].alert_id == allowed_row.alert_id
    assert result.status_counts == {"active": 1, "acknowledged": 0, "resolved": 0}


@pytest.mark.asyncio
async def test_list_alerts_total_counts_every_match_beyond_the_limit(mock_db, fake_redis):
    # Regression: total used to be len(items), i.e. never more than the limit.
    scope = {"workspace_id": str(WORKSPACE)}
    service = _scoped_list_service(mock_db, fake_redis, [_make_alert_row(scope=scope), _make_alert_row(scope=scope)],
                                   {"active": 250, "acknowledged": 3, "resolved": 1000})
    result = await service.list_alerts(status_filter=None, severity_filter=None, source_filter=None,
        correlation_id_filter=None, search_filter=None, limit=2, actor_user_id=str(uuid.uuid4()))
    assert len(result.items) == 2
    assert result.total == 1253
    assert result.status_counts == {"active": 250, "acknowledged": 3, "resolved": 1000}


@pytest.mark.asyncio
async def test_list_alerts_final_recheck_is_batched_not_per_row(mock_db, fake_redis):
    # Regression (N+1): 200 rows used to trigger ~4 owner queries each.
    rows = [_make_alert_row(scope={"workspace_id": str(WORKSPACE), "network_id": str(NETWORKS[i % 2])})
            for i in range(200)]
    service = _scoped_list_service(mock_db, fake_redis, rows, {"active": 200})
    result = await service.list_alerts(status_filter=None, severity_filter=None, source_filter=None,
        correlation_id_filter=None, search_filter=None, limit=200, actor_user_id=str(uuid.uuid4()))
    assert result.total == 200 and len(result.items) == 200
    service._workspace_svc.list_accessible_workspace_ids.assert_awaited_once()
    service._network_svc.list_networks.assert_awaited_once()  # one listing per recorded workspace
    service._assert_alert_access.assert_not_awaited()


@pytest.mark.asyncio
async def test_list_alerts_drops_rows_of_deleted_or_foreign_networks_and_revoked_workspaces(mock_db, fake_redis):
    active, gone = NETWORKS
    rows = [
        _make_alert_row(scope={"workspace_id": str(WORKSPACE)}),
        _make_alert_row(scope={"workspace_id": str(WORKSPACE), "network_id": str(active)}),
        # Deleted, or recorded under this workspace but owned by another one.
        _make_alert_row(scope={"workspace_id": str(WORKSPACE), "network_id": str(gone)}),
    ]
    service = _scoped_list_service(mock_db, fake_redis, rows, {"active": 3})
    service._network_svc.list_networks = AsyncMock(return_value=SimpleNamespace(
        items=[SimpleNamespace(network_id=active)], total=1))
    result = await service.list_alerts(status_filter=None, severity_filter=None, source_filter=None,
        correlation_id_filter=None, search_filter=None, limit=10, actor_user_id=str(uuid.uuid4()))
    assert [item.alert_id for item in result.items] == [rows[0].alert_id, rows[1].alert_id]
    assert result.total == 2
    # Membership revoked while the request ran: the single fresh read removes everything.
    service._workspace_svc.list_accessible_workspace_ids = AsyncMock(return_value=[])
    result = await service.list_alerts(status_filter=None, severity_filter=None, source_filter=None,
        correlation_id_filter=None, search_filter=None, limit=10, actor_user_id=str(uuid.uuid4()))
    assert result.items == [] and result.total == 0


@pytest.mark.asyncio
async def test_list_alerts_rejects_overlong_search_before_querying(mock_db, fake_redis):
    service = _scoped_list_service(mock_db, fake_redis, [], {})
    with pytest.raises(HTTPException) as error:
        await service.list_alerts(status_filter=None, severity_filter=None, source_filter=None,
            correlation_id_filter=None, search_filter="x" * 201, limit=10, actor_user_id=str(uuid.uuid4()))
    assert error.value.status_code == 400 and error.value.detail["code"] == "ALERT_SEARCH_INVALID"
    service._repo.list_alerts.assert_not_awaited()
    service._accessible_scopes.assert_not_awaited()


@pytest.mark.asyncio
async def test_list_alerts_rejects_invalid_status_filter(mock_db, fake_redis):
    service = AlertService(db=mock_db, redis=fake_redis)

    with pytest.raises(HTTPException) as exc_info:
        await service.list_alerts(
            status_filter="queued",
            severity_filter=None,
            source_filter=None,
            correlation_id_filter=None,
            search_filter=None,
            limit=20,
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["code"] == "ALERT_STATUS_INVALID"


@pytest.mark.asyncio
async def test_acknowledge_alert_returns_404_when_not_found(mock_db, fake_redis):
    service = AlertService(db=mock_db, redis=fake_redis)
    service._repo.get_by_id = AsyncMock(return_value=None)

    with pytest.raises(HTTPException) as exc_info:
        await service.acknowledge_alert(
            alert_id=uuid.uuid4(),
            correlation_id=str(uuid.uuid4()),
            requested_by_user_id=str(uuid.uuid4()),
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail["code"] == "ALERT_NOT_FOUND"


@pytest.mark.asyncio
async def test_acknowledge_alert_rejects_resolved_alert(mock_db, fake_redis):
    service = AlertService(db=mock_db, redis=fake_redis)
    service._repo.get_by_id = AsyncMock(return_value=_make_alert_row(status="resolved"))
    service._assert_alert_access = AsyncMock(return_value=None)

    with pytest.raises(HTTPException) as exc_info:
        await service.acknowledge_alert(
            alert_id=uuid.uuid4(),
            correlation_id=str(uuid.uuid4()),
            requested_by_user_id=str(uuid.uuid4()),
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "ALERT_ALREADY_RESOLVED"


@pytest.mark.asyncio
async def test_acknowledge_alert_returns_idempotent_replay_when_already_acknowledged(mock_db, fake_redis):
    row = _make_alert_row(status="acknowledged")
    service = AlertService(db=mock_db, redis=fake_redis)
    service._repo.get_by_id = AsyncMock(return_value=row)
    service._repo.mark_acknowledged = AsyncMock()
    service._assert_alert_access = AsyncMock(return_value=None)

    result = await service.acknowledge_alert(
        alert_id=row.alert_id,
        correlation_id=str(uuid.uuid4()),
        requested_by_user_id=str(uuid.uuid4()),
    )

    assert result.idempotent_replay is True
    assert result.queue_status == "replayed"
    service._repo.mark_acknowledged.assert_not_awaited()


@pytest.mark.asyncio
async def test_acknowledge_alert_commits_state_history_and_outbox(mock_db, fake_redis):
    row = _make_alert_row(status="active")
    actor_id = str(uuid.uuid4())
    service = AlertService(db=mock_db, redis=fake_redis)
    service._repo.get_by_id = AsyncMock(return_value=row)
    service._assert_alert_access = AsyncMock(return_value=None)

    async def _mark_ack(
        target,
        *,
        acknowledged_by_user_id,
        acknowledged_at,
        payload,
        acknowledged_event_id,
    ):
        target.status = "acknowledged"
        target.acknowledged_by_user_id = acknowledged_by_user_id
        target.acknowledged_at = acknowledged_at
        target.payload = payload
        target.acknowledged_event_id = acknowledged_event_id
        return target

    service._repo.mark_acknowledged = AsyncMock(side_effect=_mark_ack)

    result = await service.acknowledge_alert(
        alert_id=row.alert_id,
        correlation_id=str(uuid.uuid4()),
        requested_by_user_id=actor_id,
    )

    assert result.idempotent_replay is False
    assert result.queue_status == "deferred"
    assert result.stream_entry_id is None
    assert result.status == "acknowledged"
    assert result.acknowledged_by_user_id == actor_id
    assert service._repo.append_history.await_args.kwargs["event_type"] == "alert.acknowledged"
    assert service._repo.append_history.await_args.kwargs["publish"] is True
    assert service._repo.append_history.await_args.kwargs["payload"]["status"] == "acknowledged"
    service._repo.get_by_id.assert_awaited_once_with(row.alert_id, lock=True)
    mock_db.commit.assert_awaited_once()
    mock_db.refresh.assert_awaited_once_with(row)


@pytest.mark.asyncio
async def test_resolve_alert_returns_idempotent_replay_when_already_resolved(mock_db, fake_redis):
    row = _make_alert_row(status="resolved")
    service = AlertService(db=mock_db, redis=fake_redis)
    service._repo.get_by_id = AsyncMock(return_value=row)
    service._repo.mark_resolved = AsyncMock()
    service._assert_alert_access = AsyncMock(return_value=None)

    result = await service.resolve_alert(
        alert_id=row.alert_id,
        correlation_id=str(uuid.uuid4()),
        requested_by_user_id=str(uuid.uuid4()),
    )

    assert result.idempotent_replay is True
    assert result.queue_status == "replayed"
    service._repo.mark_resolved.assert_not_awaited()


@pytest.mark.asyncio
async def test_resolve_alert_delivery_is_deferred_to_durable_worker(mock_db, fake_redis):
    row = _make_alert_row(status="active")
    actor_id = str(uuid.uuid4())
    service = AlertService(db=mock_db, redis=fake_redis)
    service._repo.get_by_id = AsyncMock(return_value=row)
    service._assert_alert_access = AsyncMock(return_value=None)

    async def _mark_resolved(
        target,
        *,
        resolved_by_user_id,
        resolved_at,
        payload,
        resolved_event_id,
    ):
        target.status = "resolved"
        target.resolved_by_user_id = resolved_by_user_id
        target.resolved_at = resolved_at
        target.payload = payload
        target.resolved_event_id = resolved_event_id
        return target

    service._repo.mark_resolved = AsyncMock(side_effect=_mark_resolved)

    result = await service.resolve_alert(
        alert_id=row.alert_id,
        correlation_id=str(uuid.uuid4()),
        requested_by_user_id=actor_id,
    )

    assert result.idempotent_replay is False
    assert result.queue_status == "deferred"
    assert result.warning == "event_delivery_pending"
    assert service._repo.append_history.await_args.kwargs["publish"] is True
    assert result.status == "resolved"
    mock_db.commit.assert_awaited_once()
    mock_db.refresh.assert_awaited_once_with(row)


@pytest.mark.asyncio
async def test_acknowledge_alert_denied_when_scope_check_fails(mock_db, fake_redis):
    row = _make_alert_row(status="active")
    service = AlertService(db=mock_db, redis=fake_redis)
    service._repo.get_by_id = AsyncMock(return_value=row)
    service._assert_alert_access = AsyncMock(
        side_effect=HTTPException(status_code=403, detail="Insufficient permissions.")
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.acknowledge_alert(
            alert_id=row.alert_id,
            correlation_id=str(uuid.uuid4()),
            requested_by_user_id=str(uuid.uuid4()),
            requested_workspace_id=uuid.uuid4(),
            claim_org_id=uuid.uuid4(),
        )

    assert exc_info.value.status_code == 403
    mock_db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_resolve_alert_denied_when_scope_check_fails(mock_db, fake_redis):
    row = _make_alert_row(status="active")
    service = AlertService(db=mock_db, redis=fake_redis)
    service._repo.get_by_id = AsyncMock(return_value=row)
    service._assert_alert_access = AsyncMock(
        side_effect=HTTPException(status_code=403, detail="Insufficient permissions.")
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.resolve_alert(
            alert_id=row.alert_id,
            correlation_id=str(uuid.uuid4()),
            requested_by_user_id=str(uuid.uuid4()),
            requested_workspace_id=uuid.uuid4(),
            claim_org_id=uuid.uuid4(),
        )

    assert exc_info.value.status_code == 403
    mock_db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_ingest_generated_event_persists_alert_record(mock_db, fake_redis):
    service = AlertService(db=mock_db, redis=fake_redis)
    service._repo.get_by_generated_event_id = AsyncMock(return_value=None)
    service._repo.get_latest_unresolved_by_key = AsyncMock(return_value=None)
    service._repo.create_generated = AsyncMock(return_value=_make_alert_row())
    event_alert_id = uuid.uuid4()

    await service.ingest_alert_event(
        {
            "event_id": str(uuid.uuid4()),
            "event_type": "alert.generated",
            "timestamp": datetime.now(UTC).isoformat(),
            "source": "telemetry",
            "correlation_id": str(uuid.uuid4()),
            "payload": {
                "alert_id": str(event_alert_id),
                "alert_key": "telemetry_runtime_adapter_slo_threshold_breach",
                "severity": "CRITICAL",
                "message": "SLO threshold exceeded",
            },
        }
    )

    create_kwargs = service._repo.create_generated.await_args.kwargs
    assert create_kwargs["alert_id"] == event_alert_id
    assert create_kwargs["source"] == "telemetry"
    assert create_kwargs["severity"] == "critical"
    assert create_kwargs["payload"]["status"] == "active"
    mock_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_ingest_generated_event_deduplicates_unresolved_by_alert_key(mock_db, fake_redis):
    service = AlertService(db=mock_db, redis=fake_redis)
    service._repo.get_by_generated_event_id = AsyncMock(return_value=None)
    service._repo.get_latest_unresolved_by_key = AsyncMock(return_value=_make_alert_row(status="active"))
    service._repo.create_generated = AsyncMock()

    await service.ingest_alert_event(
        {
            "event_id": str(uuid.uuid4()),
            "event_type": "alert.generated",
            "source": "telemetry",
            "correlation_id": str(uuid.uuid4()),
            "timestamp": datetime.now(UTC).isoformat(),
            "payload": {
                "alert_key": "telemetry_runtime_adapter_slo_threshold_breach",
                "severity": "critical",
            },
        }
    )

    service._repo.create_generated.assert_not_awaited()
    service._repo.link_consumed_generation.assert_awaited_once()
    mock_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_ingest_acknowledged_event_updates_target_status(mock_db, fake_redis):
    target = _make_alert_row(status="active")
    actor_id = str(uuid.uuid4())
    service = AlertService(db=mock_db, redis=fake_redis)
    service._repo.get_by_id = AsyncMock(return_value=target)

    async def _mark_ack(
        target_row,
        *,
        acknowledged_by_user_id,
        acknowledged_at,
        payload,
        acknowledged_event_id,
    ):
        target_row.status = "acknowledged"
        target_row.acknowledged_by_user_id = acknowledged_by_user_id
        target_row.acknowledged_at = acknowledged_at
        target_row.payload = payload
        target_row.acknowledged_event_id = acknowledged_event_id
        return target_row

    service._repo.mark_acknowledged = AsyncMock(side_effect=_mark_ack)

    await service.ingest_alert_event(
        {
            "event_id": str(uuid.uuid4()),
            "event_type": "alert.acknowledged",
            "source": "alert",
            "correlation_id": str(uuid.uuid4()),
            "timestamp": datetime.now(UTC).isoformat(),
            "payload": {
                "alert_id": str(target.alert_id),
                "acknowledged_by_user_id": actor_id,
            },
        }
    )

    assert target.status == "acknowledged"
    assert target.acknowledged_by_user_id == actor_id
    service._repo.mark_acknowledged.assert_awaited_once()
    mock_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_ingest_resolved_event_uses_alert_key_lookup_when_id_missing(mock_db, fake_redis):
    target = _make_alert_row(status="acknowledged")
    actor_id = str(uuid.uuid4())
    service = AlertService(db=mock_db, redis=fake_redis)
    service._repo.get_latest_unresolved_by_key = AsyncMock(return_value=target)

    async def _mark_resolved(
        target_row,
        *,
        resolved_by_user_id,
        resolved_at,
        payload,
        resolved_event_id,
    ):
        target_row.status = "resolved"
        target_row.resolved_by_user_id = resolved_by_user_id
        target_row.resolved_at = resolved_at
        target_row.payload = payload
        target_row.resolved_event_id = resolved_event_id
        return target_row

    service._repo.mark_resolved = AsyncMock(side_effect=_mark_resolved)

    await service.ingest_alert_event(
        {
            "event_id": str(uuid.uuid4()),
            "event_type": "alert.resolved",
            "source": "alert",
            "correlation_id": str(uuid.uuid4()),
            "timestamp": datetime.now(UTC).isoformat(),
            "payload": {
                "alert_key": target.alert_key,
                "resolved_by_user_id": actor_id,
            },
        }
    )

    assert target.status == "resolved"
    assert target.resolved_by_user_id == actor_id
    service._repo.mark_resolved.assert_awaited_once()
    mock_db.commit.assert_awaited_once()


def _opaque_uuid(value: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"nanfo:audit-correlation:{value}")


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,marker", [("acknowledge_alert", "mark_acknowledged"),
                                               ("resolve_alert", "mark_resolved")])
@pytest.mark.parametrize("request_id", ["req_ack/42", str(uuid.UUID(int=42)), "{00000000-0000-0000-0000-00000000002A}"])
async def test_actions_map_request_id_with_shared_correlation_and_keep_original(
    mock_db, fake_redis, operation, marker, request_id,
):
    # Regression: opaque request ids used to become a random uuid4 (untraceable).
    row = _make_alert_row(status="active", scope={"workspace_id": str(WORKSPACE)})
    service = AlertService(db=mock_db, redis=fake_redis)
    service._repo.get_by_id = AsyncMock(return_value=row)
    service._assert_alert_access = AsyncMock(return_value=None)
    setattr(service._repo, marker, AsyncMock(return_value=row))

    await getattr(service, operation)(alert_id=row.alert_id, correlation_id=request_id,
                                      requested_by_user_id=str(uuid.uuid4()))

    history = service._repo.append_history.await_args.kwargs
    state_payload = getattr(service._repo, marker).await_args.kwargs["payload"]
    if request_id.startswith("req_"):
        assert history["correlation_id"] == _opaque_uuid(request_id)
        assert history["payload"]["request_id"] == request_id
    else:
        assert history["correlation_id"] == uuid.UUID(int=42)
        # Canonical UUIDs carry no metadata; non-canonical spellings keep the original.
        assert history["payload"].get("request_id") == (None if request_id == str(uuid.UUID(int=42)) else request_id)
    # Request provenance is event metadata, never merged into the alert state.
    assert "request_id" not in state_payload


@pytest.mark.asyncio
async def test_ingested_opaque_correlation_is_deterministic_not_random(mock_db, fake_redis):
    service = AlertService(db=mock_db, redis=fake_redis)
    service._repo.get_by_generated_event_id = AsyncMock(return_value=None)
    service._repo.get_latest_unresolved_by_key = AsyncMock(return_value=None)
    service._repo.create_generated = AsyncMock(return_value=_make_alert_row())
    await service.ingest_alert_event({
        "event_id": str(uuid.uuid4()), "event_type": "alert.generated", "source": "telemetry",
        "correlation_id": "legacy-producer/7", "timestamp": datetime.now(UTC).isoformat(),
        "payload": {"alert_key": "legacy", "workspace_id": str(WORKSPACE)},
    })
    assert service._repo.create_generated.await_args.kwargs["correlation_id"] == _opaque_uuid("legacy-producer/7")
    history = service._repo.append_history.await_args.kwargs
    assert history["correlation_id"] == _opaque_uuid("legacy-producer/7")
    assert history["payload"]["request_id"] == "legacy-producer/7"
    assert "request_id" not in service._repo.create_generated.await_args.kwargs["payload"]


# ── Platform-scoped SLO alerts (ADR-028, BE-Telemetry request) ───────────────

def _slo_payload(event_type="alert.generated", active=True):
    from app.modules.telemetry.slo.rules import alert_payload

    window = {"start": "2026-09-23T00:00:00+00:00", "end": "2026-09-23T00:00:30+00:00", "seconds": 30.0,
              "counter_reset": False, "last_batch_size": 5, "invalid_samples": 0, "dropped_samples": 3,
              "ingest_attempts": 5, "ingest_failures": 0}
    return alert_payload(event_type=event_type, previous_active=not active, current_active=active,
                         severity="warning" if active else "ok", severity_reason="anomaly_streak_threshold_exceeded",
                         flags=["dropped_samples"], window=window)


def _platform_row(**overrides):
    row = _make_alert_row(scope={**_slo_payload(), "workspace_id": None, "network_id": None, "org_id": None})
    for key, value in overrides.items():
        setattr(row, key, value)
    return row


def _platform_list_service(mock_db, fake_redis, rows, counts):
    service = AlertService(db=mock_db, redis=fake_redis)
    service._member_org_ids = AsyncMock(return_value=[])  # a global Admin need not be an org member
    service._workspace_svc.list_accessible_workspace_ids = AsyncMock(return_value=[])
    service._repo.legacy_network_ids = AsyncMock(return_value=[])
    service._repo.list_alerts = AsyncMock(return_value=rows)
    service._repo.count_alerts = AsyncMock(return_value=counts)
    return service


@pytest.mark.asyncio
async def test_global_admin_lists_platform_alerts_with_their_evaluation_window(mock_db, fake_redis):
    platform = _platform_row()
    service = _platform_list_service(mock_db, fake_redis, [platform], {"active": 1})
    result = await service.list_alerts(status_filter=None, severity_filter=None, source_filter=None,
        correlation_id_filter=None, search_filter=None, limit=50, actor_user_id=str(uuid.uuid4()),
        platform_reader=True)
    scope = service._repo.list_alerts.await_args.kwargs["scope"]
    assert scope.platform and not scope.empty
    assert service._repo.count_alerts.await_args.kwargs["scope"] is scope
    assert [item.alert_id for item in result.items] == [platform.alert_id] and result.total == 1
    item = result.items[0]
    assert item.payload["alert_scope"] == "platform"
    assert item.payload["evaluation_window"] == {"start": "2026-09-23T00:00:00+00:00",
                                                 "end": "2026-09-23T00:00:30+00:00", "seconds": 30.0,
                                                 "counter_reset": False}


@pytest.mark.asyncio
@pytest.mark.parametrize("narrowing", [
    {"platform_reader": False},
    {"platform_reader": True, "claim_org_id": ORG},
    {"platform_reader": True, "requested_workspace_id": WORKSPACE},
    {"platform_reader": True, "workspace_id_filter": WORKSPACE},
    {"platform_reader": True, "network_id_filter": NETWORKS[0]},
], ids=["tenant", "org-scoped-token", "workspace-scoped-token", "workspace-selection", "network-selection"])
async def test_platform_alerts_never_reach_tenant_or_narrowed_views(mock_db, fake_redis, narrowing):
    platform = _platform_row()
    service = _platform_list_service(mock_db, fake_redis, [platform], {"active": 1})
    service._member_org_ids = AsyncMock(return_value=[ORG])
    service._workspace_svc.list_accessible_workspace_ids = AsyncMock(return_value=[WORKSPACE])
    service._workspace_svc.get_active_workspace = AsyncMock(return_value=SimpleNamespace(org_id=ORG))
    service._network_svc.assert_network_workspace_access = AsyncMock(
        return_value=SimpleNamespace(workspace_id=WORKSPACE))
    result = await service.list_alerts(status_filter=None, severity_filter=None, source_filter=None,
        correlation_id_filter=None, search_filter=None, limit=50, actor_user_id=str(uuid.uuid4()), **narrowing)
    assert service._repo.list_alerts.await_args.kwargs["scope"].platform is False
    # Even if a platform row came back, the in-memory recheck removes it.
    assert result.items == [] and result.total == 0


@pytest.mark.asyncio
async def test_platform_alert_detail_and_history_are_global_admin_reads_only(mock_db, fake_redis):
    platform = _platform_row()
    service = AlertService(db=mock_db, redis=fake_redis)
    service._repo.get_by_id = AsyncMock(return_value=platform)
    service._repo.history = AsyncMock(return_value=[])
    detail = await service.get_alert(alert_id=platform.alert_id, actor_user_id="admin", platform_reader=True)
    assert detail.payload["evaluation_window"]["seconds"] == 30.0
    history = await service.get_history(alert_id=platform.alert_id, actor_user_id="admin", platform_reader=True)
    assert history.alert_id == platform.alert_id and history.total == 0
    for kwargs in ({"platform_reader": False}, {"platform_reader": True, "claim_org_id": ORG},
                   {"platform_reader": True, "requested_workspace_id": WORKSPACE}):
        with pytest.raises(HTTPException) as denied:
            await service.get_alert(alert_id=platform.alert_id, actor_user_id="user", **kwargs)
        assert denied.value.status_code == 403
    # Lifecycle belongs to the SLO evaluator: nobody acknowledges/resolves it by hand.
    for action in (service.acknowledge_alert, service.resolve_alert):
        with pytest.raises(HTTPException) as denied:
            await action(alert_id=platform.alert_id, correlation_id=str(uuid.uuid4()), requested_by_user_id="admin")
        assert denied.value.status_code == 403
    mock_db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_slo_generation_and_resolution_pass_the_evaluation_window_through(mock_db, fake_redis):
    from app.modules.alert.scope import is_platform_scoped, scope_columns

    service = AlertService(db=mock_db, redis=fake_redis)
    service._repo.get_by_generated_event_id = AsyncMock(return_value=None)
    service._repo.get_latest_unresolved_by_key = AsyncMock(return_value=None)
    service._repo.create_generated = AsyncMock(return_value=_make_alert_row())
    await service.ingest_alert_event({"event_id": str(uuid.uuid4()), "event_type": "alert.generated",
                                      "source": "telemetry", "correlation_id": str(uuid.uuid4()),
                                      "timestamp": "2026-09-23T00:00:30+00:00", "payload": _slo_payload()})
    stored = service._repo.create_generated.await_args.kwargs["payload"]
    assert is_platform_scoped(stored) and stored["evaluation_window"]["end"] == "2026-09-23T00:00:30+00:00"
    assert scope_columns(stored) == {"org_id": None, "workspace_id": None, "network_id": None}

    target = _platform_row(created_at=datetime(2026, 9, 23, tzinfo=UTC))
    service._repo.get_latest_unresolved_by_key = AsyncMock(return_value=target)
    service._repo.mark_resolved = AsyncMock()
    resolved = _slo_payload("alert.resolved", active=False)
    resolved["evaluation_window"]["end"] = "2026-09-23T00:05:00+00:00"
    await service.ingest_alert_event({"event_id": str(uuid.uuid4()), "event_type": "alert.resolved",
                                      "source": "telemetry", "correlation_id": str(uuid.uuid4()),
                                      "timestamp": "2026-09-23T00:05:00+00:00", "payload": resolved})
    merged = service._repo.mark_resolved.await_args.kwargs["payload"]
    assert merged["status"] == "resolved" and merged["evaluation_window"]["end"] == "2026-09-23T00:05:00+00:00"
    assert is_platform_scoped(merged)


@pytest.mark.asyncio
async def test_network_listings_are_reused_between_legacy_resolution_and_recheck(mock_db, fake_redis):
    rows = [_make_alert_row(scope={"workspace_id": str(WORKSPACE), "network_id": str(NETWORKS[0])}),
            _make_alert_row(scope={"network_id": str(NETWORKS[1])})]  # legacy network-only scope
    service = AlertService(db=mock_db, redis=fake_redis)
    service._member_org_ids = AsyncMock(return_value=[ORG])
    service._workspace_svc.list_accessible_workspace_ids = AsyncMock(return_value=[WORKSPACE])
    # More distinct legacy networks than workspaces: one listing per workspace, not per network.
    service._repo.legacy_network_ids = AsyncMock(return_value=[NETWORKS[1], uuid.UUID(int=699)])
    service._network_svc.list_networks = AsyncMock(return_value=SimpleNamespace(
        items=[SimpleNamespace(network_id=network) for network in NETWORKS], total=len(NETWORKS)))
    service._network_svc.assert_network_workspace_access = AsyncMock(side_effect=AssertionError("per-network"))
    service._repo.list_alerts = AsyncMock(return_value=rows)
    service._repo.count_alerts = AsyncMock(return_value={"active": 2})
    result = await service.list_alerts(status_filter=None, severity_filter=None, source_filter=None,
        correlation_id_filter=None, search_filter=None, limit=10, actor_user_id=str(uuid.uuid4()))
    assert [item.alert_id for item in result.items] == [row.alert_id for row in rows] and result.total == 2
    assert service._repo.list_alerts.await_args.kwargs["scope"].networks == {NETWORKS[1]: WORKSPACE}
    service._network_svc.list_networks.assert_awaited_once()  # reused by the final recheck

"""Unit tests for alert service lifecycle and ingestion behavior."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.modules.alert.service import AlertService


def _make_alert_row(
    *,
    alert_id: uuid.UUID | None = None,
    alert_key: str = "telemetry_runtime_adapter_slo_threshold_breach",
    status: str = "active",
    severity: str | None = "critical",
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
        },
        acknowledged_by_user_id=None,
        resolved_by_user_id=None,
        acknowledged_at=None,
        resolved_at=None,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_list_alerts_normalizes_filters_and_returns_status_counts(mock_db, fake_redis):
    service = AlertService(db=mock_db, redis=fake_redis)
    service._assert_alert_access = AsyncMock(return_value=None)
    service._repo.list_alerts = AsyncMock(
        return_value=[
            _make_alert_row(status="active"),
            _make_alert_row(status="ACKNOWLEDGED"),
            _make_alert_row(status="resolved"),
        ]
    )

    result = await service.list_alerts(
        status_filter="ACTIVE",
        severity_filter="CRITICAL",
        source_filter="Telemetry",
        correlation_id_filter=uuid.uuid4(),
        search_filter="  link down  ",
        limit=999,
        actor_user_id=str(uuid.uuid4()),
        requested_workspace_id=uuid.uuid4(),
        claim_org_id=uuid.uuid4(),
    )

    assert result.total == 3
    assert result.status_counts["active"] == 1
    assert result.status_counts["acknowledged"] == 1
    assert result.status_counts["resolved"] == 1
    assert service._repo.list_alerts.await_args.kwargs["status"] == "active"
    assert service._repo.list_alerts.await_args.kwargs["severity"] == "critical"
    assert service._repo.list_alerts.await_args.kwargs["source"] == "telemetry"
    assert service._repo.list_alerts.await_args.kwargs["search"] == "link down"
    assert service._repo.list_alerts.await_args.kwargs["limit"] == 500
    assert service._assert_alert_access.await_count == 3


@pytest.mark.asyncio
async def test_list_alerts_filters_out_forbidden_alert_rows(mock_db, fake_redis):
    service = AlertService(db=mock_db, redis=fake_redis)
    allowed_row = _make_alert_row(status="active")
    denied_row = _make_alert_row(status="resolved")
    service._repo.list_alerts = AsyncMock(return_value=[allowed_row, denied_row])

    async def _access_check(*, alert, actor_user_id, requested_workspace_id, claim_org_id):
        if alert.alert_id == denied_row.alert_id:
            raise HTTPException(status_code=403, detail="Insufficient permissions.")

    service._assert_alert_access = AsyncMock(side_effect=_access_check)

    result = await service.list_alerts(
        status_filter=None,
        severity_filter=None,
        source_filter=None,
        correlation_id_filter=None,
        search_filter=None,
        limit=50,
        actor_user_id=str(uuid.uuid4()),
        requested_workspace_id=uuid.uuid4(),
        claim_org_id=uuid.uuid4(),
    )

    assert result.total == 1
    assert len(result.items) == 1
    assert result.items[0].alert_id == allowed_row.alert_id


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
async def test_acknowledge_alert_marks_state_and_publishes_event(mock_db, fake_redis):
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

    with patch("app.modules.alert.service.publish_event", new_callable=AsyncMock) as mock_publish:
        mock_publish.return_value = "500-0"
        result = await service.acknowledge_alert(
            alert_id=row.alert_id,
            correlation_id=str(uuid.uuid4()),
            requested_by_user_id=actor_id,
        )

    assert result.idempotent_replay is False
    assert result.queue_status == "queued"
    assert result.stream_entry_id == "500-0"
    assert result.status == "acknowledged"
    assert result.acknowledged_by_user_id == actor_id
    assert mock_publish.await_args.kwargs["event_type"] == "alert.acknowledged"
    assert mock_publish.await_args.kwargs["payload"]["status"] == "acknowledged"
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
async def test_resolve_alert_publish_failure_is_fail_open(mock_db, fake_redis):
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

    with patch("app.modules.alert.service.publish_event", new_callable=AsyncMock) as mock_publish:
        mock_publish.side_effect = RuntimeError("stream unavailable")
        result = await service.resolve_alert(
            alert_id=row.alert_id,
            correlation_id=str(uuid.uuid4()),
            requested_by_user_id=actor_id,
        )

    assert result.idempotent_replay is False
    assert result.queue_status == "deferred"
    assert result.warning == "event_queue_unavailable"
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
    mock_db.commit.assert_not_awaited()


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

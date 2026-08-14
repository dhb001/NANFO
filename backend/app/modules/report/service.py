"""Report services.

Scope:
- Reporting async generation/status baseline
- Queue-backed artifact lifecycle tracking
- Fail-open report event publication for report.* contracts
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Any

import redis.asyncio as aioredis
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.events.publisher import publish_event
from app.modules.network.repository import NetworkRepository
from app.modules.organization.service import WorkspaceService as OrgWorkspaceService
from app.modules.report.repository import ReportRepository

logger = get_logger(__name__)

_REPORT_STATUS_REQUESTED = "requested"
_REPORT_STATUS_GENERATED = "generated"
_REPORT_STATUS_FAILED = "failed"
_TERMINAL_STATUSES = {_REPORT_STATUS_GENERATED, _REPORT_STATUS_FAILED}
_SUPPORTED_FORMATS = {"pdf", "csv"}


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _coerce_correlation_uuid(value: Any) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return uuid.uuid4()


def _coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    text = _normalize_text(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _normalize_report_format(value: str) -> str:
    return _normalize_text(value).lower()


def _as_dict(value: Any) -> dict:
    if isinstance(value, dict):
        return dict(value)
    return {}


def _as_list(value: Any) -> list:
    if isinstance(value, list):
        return list(value)
    return []


class ReportService:
    """Generate and read report lifecycle records with queue-backed transitions."""

    def __init__(self, *, db: AsyncSession, redis: aioredis.Redis | None):
        self._db = db
        self._redis = redis
        self._repo = ReportRepository(db)
        self._network_repo = NetworkRepository(db)
        self._workspace_svc = OrgWorkspaceService(db=db, redis=redis)

    async def generate_report(
        self,
        *,
        workspace_id: uuid.UUID,
        network_id: uuid.UUID | None,
        report_type: str,
        output_format: str,
        date_range: dict,
        scope: dict,
        filters: dict,
        fail_generation: bool,
        idempotency_key: str | None,
        correlation_id: str,
        requested_by_user_id: str,
    ) -> dict[str, Any]:
        await self._workspace_svc.get_active_workspace(workspace_id)

        if network_id is not None:
            network = await self._network_repo.get_by_id(network_id)
            if network is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={
                        "code": "REPORT_NETWORK_NOT_FOUND",
                        "message": "network_id does not reference an active network.",
                    },
                )
            if network.workspace_id != workspace_id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "code": "REPORT_NETWORK_WORKSPACE_MISMATCH",
                        "message": "network_id is outside the requested workspace boundary.",
                    },
                )

        normalized_format = _normalize_report_format(output_format)
        if normalized_format not in _SUPPORTED_FORMATS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "REPORT_FORMAT_UNSUPPORTED",
                    "message": "format must be one of: pdf, csv.",
                },
            )

        start = _coerce_datetime(_as_dict(date_range).get("start"))
        end = _coerce_datetime(_as_dict(date_range).get("end"))
        if start is None or end is None or start > end:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "REPORT_DATE_RANGE_INVALID",
                    "message": "date_range.start and date_range.end must be valid timestamps with start <= end.",
                },
            )

        normalized_report_type = _normalize_text(report_type)
        normalized_date_range = {
            "start": start.isoformat(),
            "end": end.isoformat(),
        }
        normalized_scope = _as_dict(scope)
        normalized_filters = _as_dict(filters)
        normalized_idempotency_key = _normalize_text(idempotency_key) or None
        normalized_correlation_id = _coerce_correlation_uuid(correlation_id)
        now = datetime.now(UTC)

        if normalized_idempotency_key is not None:
            existing = await self._repo.get_by_idempotency_key(
                workspace_id=workspace_id,
                idempotency_key=normalized_idempotency_key,
            )
            if existing is not None:
                if not self._is_same_generation_request(
                    existing,
                    network_id=network_id,
                    report_type=normalized_report_type,
                    output_format=normalized_format,
                    date_range=normalized_date_range,
                    scope=normalized_scope,
                    filters=normalized_filters,
                ):
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail={
                            "code": "REPORT_IDEMPOTENCY_CONFLICT",
                            "message": "idempotency_key is already bound to a different report request.",
                        },
                    )
                return self._serialize_report(existing, idempotent_replay=True)

        record = await self._repo.create(
            report_id=uuid.uuid4(),
            workspace_id=workspace_id,
            network_id=network_id,
            report_type=normalized_report_type,
            output_format=normalized_format,
            status=_REPORT_STATUS_REQUESTED,
            date_range=normalized_date_range,
            scope=normalized_scope,
            filters=normalized_filters,
            artifact_refs=[],
            error_context={},
            queue_status="pending",
            stream_entry_id=None,
            warning=None,
            idempotency_key=normalized_idempotency_key,
            correlation_id=normalized_correlation_id,
            requested_by_user_id=requested_by_user_id,
            requested_at=now,
        )
        await self._db.commit()
        await self._db.refresh(record)

        queue_status, stream_entry_id, warning = await self._publish_lifecycle_event(
            event_type="report.requested",
            correlation_id=correlation_id,
            payload=self._build_requested_event_payload(
                record,
                fail_generation=fail_generation,
            ),
        )

        await self._repo.update_lifecycle(
            record,
            status=_REPORT_STATUS_REQUESTED,
            queue_status=queue_status,
            stream_entry_id=stream_entry_id,
            warning=warning,
        )
        await self._db.commit()
        await self._db.refresh(record)

        return self._serialize_report(record, idempotent_replay=False)

    async def get_report(
        self,
        *,
        report_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> dict[str, Any]:
        await self._workspace_svc.get_active_workspace(workspace_id)
        record = await self._repo.get_by_id(report_id)
        if record is None or record.workspace_id != workspace_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "REPORT_NOT_FOUND", "message": "Report not found."},
            )
        return self._serialize_report(record, idempotent_replay=False)

    async def process_requested_event(self, event: dict[str, Any]) -> None:
        event_type = _normalize_text(event.get("event_type"))
        if event_type != "report.requested":
            return

        payload = _as_dict(event.get("payload"))
        report_id_raw = payload.get("report_id")
        try:
            report_id = uuid.UUID(str(report_id_raw))
        except (TypeError, ValueError, AttributeError):
            logger.warning(
                "report_event_missing_report_id",
                event_type=event_type,
                payload=payload,
            )
            return

        record = await self._repo.get_by_id(report_id)
        if record is None:
            logger.warning(
                "report_event_report_not_found",
                event_type=event_type,
                report_id=str(report_id),
            )
            return

        if _normalize_text(record.status) in _TERMINAL_STATUSES:
            return

        fail_generation = bool(payload.get("fail_generation"))
        completed_at = datetime.now(UTC)
        if fail_generation:
            terminal_status = _REPORT_STATUS_FAILED
            artifacts: list[dict[str, Any]] = []
            error_context = {
                "code": "REPORT_GENERATION_FAILED",
                "message": "Report generation failed during queue processing.",
                "failed_at": completed_at.isoformat(),
            }
        else:
            terminal_status = _REPORT_STATUS_GENERATED
            artifacts = self._build_artifacts(record=record, generated_at=completed_at)
            error_context = {}

        terminal_event_type = f"report.{terminal_status}"
        queue_status, stream_entry_id, warning = await self._publish_lifecycle_event(
            event_type=terminal_event_type,
            correlation_id=str(event.get("correlation_id", "")),
            payload=self._build_terminal_event_payload(
                record,
                status=terminal_status,
                artifacts=artifacts,
                error_context=error_context,
                completed_at=completed_at,
            ),
        )

        await self._repo.update_lifecycle(
            record,
            status=terminal_status,
            queue_status=queue_status,
            stream_entry_id=stream_entry_id,
            warning=warning,
            artifact_refs=artifacts,
            error_context=error_context,
            completed_at=completed_at,
        )
        await self._db.commit()

    @staticmethod
    def _is_same_generation_request(
        record,
        *,
        network_id: uuid.UUID | None,
        report_type: str,
        output_format: str,
        date_range: dict,
        scope: dict,
        filters: dict,
    ) -> bool:
        return (
            record.network_id == network_id
            and _normalize_text(record.report_type) == report_type
            and _normalize_text(record.output_format) == output_format
            and _as_dict(record.date_range) == date_range
            and _as_dict(record.scope) == scope
            and _as_dict(record.filters) == filters
        )

    @staticmethod
    def _build_artifacts(*, record, generated_at: datetime) -> list[dict[str, Any]]:
        settings = get_settings()
        extension = _normalize_report_format(record.output_format)
        media_type = "application/pdf" if extension == "pdf" else "text/csv"
        content_fingerprint = (
            f"{record.report_id}:{record.workspace_id}:{record.report_type}:{record.output_format}:{generated_at.isoformat()}"
        )
        checksum = hashlib.sha256(content_fingerprint.encode("utf-8")).hexdigest()
        size_bytes = 16384 if extension == "pdf" else 8192
        artifact_id = f"artifact-{record.report_id}-{extension}"
        uri = f"s3://{settings.REPORTS_ARTIFACT_BUCKET}/{record.workspace_id}/{record.report_id}.{extension}"
        return [
            {
                "artifact_id": artifact_id,
                "uri": uri,
                "media_type": media_type,
                "checksum_sha256": checksum,
                "size_bytes": size_bytes,
                "generated_at": generated_at.isoformat(),
            }
        ]

    def _build_requested_event_payload(
        self,
        record,
        *,
        fail_generation: bool,
    ) -> dict[str, Any]:
        return {
            "report_id": str(record.report_id),
            "workspace_id": str(record.workspace_id),
            "network_id": str(record.network_id) if record.network_id is not None else None,
            "report_type": _normalize_text(record.report_type),
            "format": _normalize_report_format(record.output_format),
            "status": _normalize_text(record.status),
            "date_range": _as_dict(record.date_range),
            "scope": _as_dict(record.scope),
            "filters": _as_dict(record.filters),
            "requested_by_user_id": _normalize_text(record.requested_by_user_id),
            "requested_at": record.requested_at.isoformat(),
            "fail_generation": fail_generation,
        }

    @staticmethod
    def _build_terminal_event_payload(
        record,
        *,
        status: str,
        artifacts: list[dict[str, Any]],
        error_context: dict[str, Any],
        completed_at: datetime,
    ) -> dict[str, Any]:
        return {
            "report_id": str(record.report_id),
            "workspace_id": str(record.workspace_id),
            "network_id": str(record.network_id) if record.network_id is not None else None,
            "report_type": _normalize_text(record.report_type),
            "format": _normalize_report_format(record.output_format),
            "status": status,
            "artifacts": artifacts,
            "error": error_context or None,
            "completed_at": completed_at.isoformat(),
            "requested_by_user_id": _normalize_text(record.requested_by_user_id),
        }

    async def _publish_lifecycle_event(
        self,
        *,
        event_type: str,
        correlation_id: str,
        payload: dict[str, Any],
    ) -> tuple[str, str | None, str | None]:
        if self._redis is None:
            return "deferred", None, "event_queue_unavailable"

        normalized_correlation_id = _coerce_correlation_uuid(correlation_id)
        try:
            stream_entry_id = await publish_event(
                redis=self._redis,
                event_type=event_type,
                source="report",
                payload=payload,
                correlation_id=str(normalized_correlation_id),
            )
            return "queued", stream_entry_id, None
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "report_lifecycle_event_publish_failed",
                event_type=event_type,
                correlation_id=str(normalized_correlation_id),
                error=str(exc),
            )
            return "deferred", None, "event_queue_unavailable"

    @staticmethod
    def _serialize_report(record, *, idempotent_replay: bool) -> dict[str, Any]:
        error_context = _as_dict(record.error_context)
        return {
            "report_id": str(record.report_id),
            "workspace_id": str(record.workspace_id),
            "network_id": str(record.network_id) if record.network_id is not None else None,
            "report_type": _normalize_text(record.report_type),
            "format": _normalize_report_format(record.output_format),
            "status": _normalize_text(record.status),
            "date_range": _as_dict(record.date_range),
            "scope": _as_dict(record.scope),
            "filters": _as_dict(record.filters),
            "artifacts": _as_list(record.artifact_refs),
            "error": error_context or None,
            "queue_status": _normalize_text(record.queue_status),
            "stream_entry_id": record.stream_entry_id,
            "warning": record.warning,
            "idempotency_key": record.idempotency_key,
            "correlation_id": str(record.correlation_id),
            "requested_by_user_id": _normalize_text(record.requested_by_user_id),
            "requested_at": record.requested_at,
            "completed_at": record.completed_at,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
            "idempotent_replay": idempotent_replay,
        }

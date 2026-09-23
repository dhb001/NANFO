"""ADR019 bounded snapshot acceptance, truthful status and authorized downloads."""

import asyncio
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.core.request_context import normalize_request_id
from app.modules.identity.service import AuthService, normalize_audit_correlation
from app.modules.network.service import NetworkService
from app.modules.organization.service import WorkspaceService
from app.modules.report.artifacts import ArtifactStore, canonical, digest, valid_receipt
from app.modules.report.models import ReportRecord
from app.modules.report.repository import ReportRepository
from app.modules.report.schemas import GenerateReportRequest
from app.modules.report.sources import ReportSources
from app.modules.telemetry.references import (
    evidence_item, install_owner_guard, page_position, reference_page,
)


def report_telemetry_references(row):
    if row.report_id is None:
        row.report_id = uuid.uuid4()
    snapshot = row.snapshot or {}
    refs = []
    unknown = "legacy_report_snapshot_unavailable" if row.artifact_version != 1 or not row.snapshot else None
    for item in snapshot.get("sections", {}).get("telemetry", {}).get("rows", []):
        if not item.get("record_id"):
            unknown = "legacy_report_record_identity_unavailable"
        refs.extend(evidence_item(identity=f"report:{row.report_id}", network_id=item.get("network_id"),
                                  fields={"snapshot": item}).references)
    from app.modules.telemetry.references import OwnerReferenceItem

    return OwnerReferenceItem(identity=str(row.report_id), references=refs,
                              unknown=unknown)


install_owner_guard(ReportRecord, owner="report", extractor=report_telemetry_references,
                    fields=("snapshot", "workspace_id", "network_id"))


async def telemetry_reference_page(db, *, workspace_id, after=None, limit=100):
    """Internal owner contract, including failed/expired reports and frozen snapshots."""
    from sqlalchemy import select

    _, last = page_position(after, stages=1, limit=limit)
    query = select(ReportRecord).where(ReportRecord.workspace_id == workspace_id)
    if last:
        query = query.where(ReportRecord.report_id > last)
    rows = list((await db.scalars(query.order_by(ReportRecord.report_id).limit(limit + 1))).all())
    return reference_page(rows, extractor=report_telemetry_references, key=lambda row: row.report_id, limit=limit)


class ReportService:
    def __init__(self, *, db, redis):
        self._db, self._redis = db, redis
        self._repo = ReportRepository(db)
        self._workspace_svc = WorkspaceService(db=db, redis=redis)

    async def authorize_generation(self, workspace_id, network_id, user_id):
        await self._workspace_svc.get_active_workspace(
            workspace_id, user_id=user_id, require_write=True
        )
        profile = await AuthService(self._db, self._redis).get_profile(user_id)
        if not {"read:telemetry", "write:config"}.issubset(profile.permissions):
            raise HTTPException(
                403,
                detail={
                    "code": "REPORT_AUTHORITY_REVOKED",
                    "message": "Report generation requires current read/write authority.",
                },
            )
        if network_id is not None:
            await NetworkService(
                db=self._db, redis=self._redis
            ).assert_network_workspace_access(
                network_id=network_id,
                requested_workspace_id=workspace_id,
                actor_user_id=user_id,
                claim_org_id=None,
                require_write=True,
            )

    async def generate_report(
        self,
        *,
        workspace_id,
        network_id,
        report_type,
        output_format,
        date_range,
        scope,
        filters,
        fail_generation,
        idempotency_key,
        correlation_id,
        requested_by_user_id,
    ):
        correlation_id, correlation_metadata = normalize_audit_correlation(
            normalize_request_id(correlation_id), {},
        )
        await self.authorize_generation(workspace_id, network_id, requested_by_user_id)
        try:
            req = GenerateReportRequest.model_validate(
                dict(
                    workspace_id=workspace_id,
                    network_id=network_id,
                    report_type=report_type,
                    format=output_format,
                    date_range=date_range,
                    scope=scope,
                    filters=filters,
                )
            )
        except ValidationError:
            raise HTTPException(
                400,
                detail={
                    "code": "REPORT_REQUEST_INVALID",
                    "message": "Unsupported report type, scope, filters, format or date range.",
                },
            ) from None
        if fail_generation:
            raise HTTPException(
                400,
                detail={
                    "code": "REPORT_REQUEST_INVALID",
                    "message": "Failure injection is not supported.",
                },
            )
        if idempotency_key is not None and (
            not 1 <= len(idempotency_key) <= 128
            or not idempotency_key.isascii()
            or not idempotency_key.isprintable()
        ):
            raise HTTPException(
                400,
                detail={
                    "code": "REPORT_IDEMPOTENCY_INVALID",
                    "message": "Idempotency-Key must be 1..128 printable ASCII characters.",
                },
            )
        normalized = req.model_dump(mode="json")

        def replay(record):
            same = (
                record.requested_by_user_id == requested_by_user_id
                and record.network_id == network_id
                and record.report_type == report_type
                and record.output_format == output_format
                and record.date_range == normalized["date_range"]
                and record.scope == normalized["scope"]
                and record.filters == normalized["filters"]
            )
            if not same:
                raise HTTPException(
                    409,
                    detail={
                        "code": "REPORT_IDEMPOTENCY_CONFLICT",
                        "message": "Idempotency key belongs to a different request.",
                    },
                )
            return self._serialize_report(record, idempotent_replay=True)

        if idempotency_key:
            existing = await self._repo.get_by_idempotency_key(
                workspace_id=workspace_id, idempotency_key=idempotency_key
            )
            if existing:
                return replay(existing)
        settings = get_settings()
        try:
            await asyncio.to_thread(
                ArtifactStore(
                    settings.REPORTS_STORAGE_PATH, settings.REPORTS_MAX_BYTES
                ).require_capacity,
                settings.REPORTS_MIN_FREE_BYTES,
            )
        except (OSError, ValueError):
            raise HTTPException(
                503,
                detail={
                    "code": "REPORT_STORAGE_UNAVAILABLE",
                    "message": "Report storage capacity is unavailable; no new report was accepted.",
                },
            ) from None
        try:
            async with asyncio.timeout(20):
                snapshot = await ReportSources(self._db, self._redis).snapshot(
                    req, requested_by_user_id
                )
                if correlation_metadata:
                    snapshot = {**snapshot, "metadata": {**snapshot.get("metadata", {}), **correlation_metadata}}
                snapshot_size = len(canonical(snapshot))
        except TimeoutError:
            raise HTTPException(
                503,
                detail={
                    "code": "REPORT_SOURCE_TIMEOUT",
                    "message": "Source reads timed out; narrow the scope and retry.",
                },
            ) from None
        except (ValueError, TypeError, KeyError):
            raise HTTPException(
                503,
                detail={
                    "code": "REPORT_SOURCE_INVALID",
                    "message": "Source export could not be validated; no report was accepted.",
                },
            ) from None
        if snapshot_size > 1048576:
            raise HTTPException(
                400,
                detail={
                    "code": "REPORT_SNAPSHOT_TOO_LARGE",
                    "message": "Snapshot exceeds 1 MiB; narrow the scope.",
                },
            )
        await self.authorize_generation(workspace_id, network_id, requested_by_user_id)
        now = datetime.now(UTC)
        record = ReportRecord(
            report_id=uuid.uuid4(),
            workspace_id=workspace_id,
            network_id=network_id,
            report_type=report_type,
            output_format=output_format,
            status="requested",
            artifact_version=1,
            status_version=1,
            date_range=normalized["date_range"],
            scope=normalized["scope"],
            filters=normalized["filters"],
            snapshot=snapshot,
            snapshot_sha256=digest(snapshot),
            artifact_refs=[],
            error_context={},
            queue_status="outbox_pending",
            requested_by_user_id=requested_by_user_id,
            requested_at=now,
            created_at=now,
            updated_at=now,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
        self._db.add(record)
        self._repo.enqueue(record)
        try:
            await self._db.commit()
        except IntegrityError:
            await self._db.rollback()
            existing = (
                await self._repo.get_by_idempotency_key(
                    workspace_id=workspace_id, idempotency_key=idempotency_key
                )
                if idempotency_key
                else None
            )
            if existing:
                return replay(existing)
            raise
        return self._serialize_report(record, idempotent_replay=False)

    async def _owned(self, report_id, workspace_id, user_id):
        await self._workspace_svc.get_active_workspace(workspace_id, user_id=user_id)
        record = await self._repo.get_by_id(report_id)
        if (
            record is None
            or record.workspace_id != workspace_id
            or record.requested_by_user_id != user_id
        ):
            raise HTTPException(
                404, detail={"code": "REPORT_NOT_FOUND", "message": "Report not found."}
            )
        return record

    async def get_report(self, *, report_id, workspace_id, user_id):
        return self._serialize_report(
            await self._owned(report_id, workspace_id, user_id), idempotent_replay=False
        )

    async def history(self, *, workspace_id, user_id, page, page_size):
        await self._workspace_svc.get_active_workspace(workspace_id, user_id=user_id)
        rows, total = await self._repo.history(workspace_id, user_id, page, page_size)
        return {
            "items": [
                self._serialize_report(row, idempotent_replay=False) for row in rows
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def download(self, *, report_id, workspace_id, user_id):
        record = await self._owned(report_id, workspace_id, user_id)
        if not valid_receipt(record):
            raise HTTPException(
                409,
                detail={
                    "code": "REPORT_ARTIFACT_UNAVAILABLE",
                    "message": "No verified generated artifact.",
                },
            )
        settings = get_settings()
        try:
            data = await asyncio.to_thread(
                ArtifactStore(
                    settings.REPORTS_STORAGE_PATH, settings.REPORTS_MAX_BYTES
                ).read,
                report_id,
                record.output_format,
                record.receipt,
            )
        except (OSError, ValueError, KeyError, TypeError):
            raise HTTPException(
                409,
                detail={
                    "code": "REPORT_ARTIFACT_INVALID",
                    "message": "Artifact missing, unsafe or checksum/size mismatch.",
                },
            ) from None
        await self._workspace_svc.get_active_workspace(workspace_id, user_id=user_id)
        return data, record.receipt

    async def process_requested_event(self, event):
        """Notification only. The durable worker discovers jobs, never consumer rendering."""
        return None

    @staticmethod
    def _serialize_report(record, *, idempotent_replay):
        state, error = record.status, record.error_context or None
        valid = valid_receipt(record)
        if state == "generated" and not valid:
            state = "failed"
            error = {
                "code": "REPORT_ARTIFACT_UNVERIFIED",
                "message": "Historical or invalid artifact metadata is unavailable.",
            }
        result = {
            key: getattr(record, key, None)
            for key in (
                "report_id",
                "workspace_id",
                "network_id",
                "report_type",
                "date_range",
                "scope",
                "filters",
                "queue_status",
                "stream_entry_id",
                "warning",
                "idempotency_key",
                "correlation_id",
                "requested_by_user_id",
                "requested_at",
                "completed_at",
                "created_at",
                "updated_at",
            )
        }
        snapshot = getattr(record, "snapshot", None) or {}
        artifacts = []
        if valid:
            artifacts = [
                {
                    key: record.receipt[key]
                    for key in (
                        "artifact_id",
                        "checksum_sha256",
                        "size_bytes",
                        "filename",
                        "media_type",
                        "generated_at",
                    )
                }
            ]
            artifacts[0]["uri"] = (
                f"/api/v1/reports/{record.report_id}/download?workspace_id={record.workspace_id}"
            )
        result.update(
            format=record.output_format,
            status=state,
            error=error,
            artifacts=artifacts,
            idempotent_replay=idempotent_replay,
            artifact_version=getattr(record, "artifact_version", 0),
            status_version=getattr(record, "status_version", 0),
            snapshot_sha256=getattr(record, "snapshot_sha256", None),
            snapshot_summary={
                name: {
                    **{key: value for key, value in contents.items() if key != "rows"},
                    "row_count": len(contents["rows"]),
                }
                for name, contents in snapshot.get("sections", {}).items()
            },
        )
        return result

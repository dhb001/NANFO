"""ADR019 bounded snapshot acceptance, truthful status and authorized downloads."""

import asyncio
import hashlib
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.core.correlation import normalize_audit_correlation
from app.core.request_context import normalize_request_id
from app.modules.identity.service import AuthService
from app.modules.network.service import NetworkService
from app.modules.organization.service import WorkspaceService
from app.modules.report.artifacts import ArtifactStore, canonical, valid_receipt
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


class ReportEventRejected(ValueError):
    """A report lifecycle notification whose content can never be processed.

    ``reason`` is a stable code; the consumer maps it to ``DeterministicEventError``.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# ADR-028 C26: per-organisation report storage (REPORTS_MAX_BYTES_PER_ORG, getattr).
DEFAULT_MAX_BYTES_PER_ORG = 512 * 1024 * 1024


def org_storage_quota(settings) -> int:
    """Per-organisation quota; invalid values use the default, never below one artifact."""
    value = getattr(settings, "REPORTS_MAX_BYTES_PER_ORG", DEFAULT_MAX_BYTES_PER_ORG)
    if isinstance(value, bool) or not isinstance(value, int):
        value = DEFAULT_MAX_BYTES_PER_ORG
    return max(value, settings.REPORTS_MAX_BYTES)


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
        """Current generation authority; returns the authorized workspace (its org)."""
        workspace = await self._workspace_svc.get_active_workspace(
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
        return workspace

    async def _admit_org_storage(self, workspace, user_id, settings, *, reserve):
        """C26: per-organisation report storage admission (in addition to the global reserve).

        Refuses (507 ``REPORT_ORG_QUOTA_EXCEEDED``) when the organisation's stored
        artifacts plus in-flight reservations plus one full new artifact would exceed
        ``REPORTS_MAX_BYTES_PER_ORG``. ``reserve=False`` is the cheap pre-check before
        source reads; ``reserve=True`` is authoritative: a per-organisation
        transaction lock serializes concurrent acceptances until this request's row
        commits (then it counts as in flight for the next one).
        """
        org_id = getattr(workspace, "org_id", None)
        if not isinstance(org_id, uuid.UUID):
            # Workspace authority always names its organisation; never skip fairness.
            raise HTTPException(503, detail={
                "code": "REPORT_STORAGE_UNAVAILABLE",
                "message": "Report storage admission is unavailable; no new report was accepted.",
            })
        workspaces = await self._workspace_svc.list_accessible_workspace_ids(user_id=user_id, claim_org_id=org_id)
        if reserve:
            await self._repo.lock_org_storage(org_id)
        used = await self._repo.storage_usage(workspaces, in_flight_reserve_bytes=settings.REPORTS_MAX_BYTES)
        if used + settings.REPORTS_MAX_BYTES > org_storage_quota(settings):
            raise HTTPException(507, detail={
                "code": "REPORT_ORG_QUOTA_EXCEEDED",
                "message": "Organisation report storage quota is exhausted; no new report was accepted.",
            })

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
        workspace = await self.authorize_generation(workspace_id, network_id, requested_by_user_id)
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

        async def replay(record):
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
            return self._serialize_report(
                record, idempotent_replay=True,
                receipt_valid=await asyncio.to_thread(valid_receipt, record),
            )

        if idempotency_key:
            existing = await self._repo.get_by_idempotency_key(
                workspace_id=workspace_id, idempotency_key=idempotency_key
            )
            if existing:
                return await replay(existing)
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
        # Cheap C26 pre-check before any source read (replays never reach it).
        await self._admit_org_storage(workspace, requested_by_user_id, settings, reserve=False)
        try:
            async with asyncio.timeout(20):
                snapshot = await ReportSources(self._db, self._redis).snapshot(
                    req, requested_by_user_id
                )
                # Request provenance never enters the frozen snapshot: the same
                # sources yield the same snapshot_sha256 and artifact bytes for any
                # request id. The original id travels in the requested event.
                encoded = await asyncio.to_thread(canonical, snapshot)
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
        if len(encoded) > 1048576:
            raise HTTPException(
                400,
                detail={
                    "code": "REPORT_SNAPSHOT_TOO_LARGE",
                    "message": "Snapshot exceeds 1 MiB; narrow the scope.",
                },
            )
        workspace = await self.authorize_generation(workspace_id, network_id, requested_by_user_id)
        # Authoritative C26 admission, serialized per organisation until commit.
        await self._admit_org_storage(workspace, requested_by_user_id, settings, reserve=True)
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
            # digest(snapshot) == sha256(canonical(snapshot)); hash the bytes once.
            snapshot_sha256=hashlib.sha256(encoded).hexdigest(),
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
        self._repo.enqueue(record, metadata=correlation_metadata)
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
                return await replay(existing)
            raise
        return self._serialize_report(record, idempotent_replay=False, receipt_valid=False)

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
        record = await self._owned(report_id, workspace_id, user_id)
        # Detail verifies the frozen snapshot hash too, off the event loop.
        return self._serialize_report(
            record, idempotent_replay=False,
            receipt_valid=await asyncio.to_thread(valid_receipt, record),
        )

    async def history(self, *, workspace_id, user_id, page, page_size):
        await self._workspace_svc.get_active_workspace(workspace_id, user_id=user_id)
        rows, total = await self._repo.history(workspace_id, user_id, page, page_size)
        return {
            "items": [
                # Summary rows carry no snapshot: receipt integrity is checked
                # against the recorded snapshot_sha256 without re-hashing 1 MiB/row.
                self._serialize_report(
                    row, idempotent_replay=False,
                    receipt_valid=valid_receipt(row, verify_snapshot=False),
                )
                for row in rows
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def download_receipt(self, *, report_id, workspace_id, user_id):
        """Owned report's verified receipt: ``(output_format, receipt)``.

        Raises 409 when there is no verified generated artifact. No artifact bytes
        are read, so conditional requests can be answered without file I/O.
        """
        record = await self._owned(report_id, workspace_id, user_id)
        if not await asyncio.to_thread(valid_receipt, record):
            raise HTTPException(
                409,
                detail={
                    "code": "REPORT_ARTIFACT_UNAVAILABLE",
                    "message": "No verified generated artifact.",
                },
            )
        return record.output_format, dict(record.receipt)

    async def open_artifact(self, *, report_id, workspace_id, user_id, output_format, receipt):
        """Verify the stored bytes (length/SHA-256, bounded chunks) and return the
        open :class:`VerifiedArtifact` to stream; membership is rechecked after I/O."""
        settings = get_settings()
        store = ArtifactStore(settings.REPORTS_STORAGE_PATH, settings.REPORTS_MAX_BYTES)
        try:
            artifact = await asyncio.to_thread(store.open_verified, report_id, output_format, receipt)
        except (OSError, ValueError, KeyError, TypeError):
            raise HTTPException(
                409,
                detail={
                    "code": "REPORT_ARTIFACT_INVALID",
                    "message": "Artifact missing, unsafe or checksum/size mismatch.",
                },
            ) from None
        try:
            await self._workspace_svc.get_active_workspace(workspace_id, user_id=user_id)
        except BaseException:
            artifact.close()
            raise
        return artifact

    async def process_requested_event(self, event):
        """Notification only. The durable worker discovers jobs, never consumer rendering.

        A notification without the report identity Report itself publishes can
        never be meaningful: it is rejected as poison (ADR-028 C14).
        """
        payload = event.get("payload") if isinstance(event, dict) else None
        if not isinstance(payload, dict):
            raise ReportEventRejected("payload_not_object")
        try:
            uuid.UUID(str(payload["report_id"]))
        except (KeyError, TypeError, ValueError, AttributeError):
            raise ReportEventRejected("invalid_report_id") from None
        return None

    @staticmethod
    def _serialize_report(record, *, idempotent_replay, receipt_valid=None):
        state, error = record.status, record.error_context or None
        valid = valid_receipt(record) if receipt_valid is None else receipt_valid
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
        summary = getattr(record, "snapshot_summary", None)
        if summary is None:
            snapshot = getattr(record, "snapshot", None) or {}
            summary = {
                name: {
                    **{key: value for key, value in contents.items() if key != "rows"},
                    "row_count": len(contents["rows"]),
                }
                for name, contents in snapshot.get("sections", {}).items()
            }
        result.update(
            format=record.output_format,
            status=state,
            error=error,
            artifacts=artifacts,
            idempotent_replay=idempotent_replay,
            artifact_version=getattr(record, "artifact_version", 0),
            status_version=getattr(record, "status_version", 0),
            snapshot_sha256=getattr(record, "snapshot_sha256", None),
            snapshot_summary=summary,
        )
        return result

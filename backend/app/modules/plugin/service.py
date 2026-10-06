"""Plugin services.

Scope:
- Metadata-only registry lifecycle (list/install/enable/disable/uninstall)
- Declaration admission checks only: a *declared* signer/signature is format- and
  allowlist-checked, never cryptographically verified (``declared_unverified``);
  no sandbox is executed
- Lifecycle events for plugin.* contracts are published only after the state they
  describe is committed (ADR-028). A failed publication leaves the row ``deferred``;
  :func:`republish_deferred_plugin_events` (run by the simulation worker process)
  republishes it with the same deterministic event ID.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import redis.asyncio as aioredis
from fastapi import HTTPException, status
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.canonical import canonical_json_bytes, canonical_sha256
from app.core.config import get_settings
from app.core.correlation import normalize_audit_correlation
from app.core.logging import get_logger
from app.events.publisher import publish_event
from app.modules.identity.service import append_audit_log
from app.modules.organization.service import OrgService, WorkspaceService
from app.modules.plugin.repository import PluginRepository
from app.modules.plugin.schemas import (
    PluginActionResponse,
    PluginInstallRequest,
    PluginListResponse,
    PluginRecordResponse,
)

logger = get_logger(__name__)

_DEFERRED = "deferred"
_QUEUE_UNAVAILABLE = "event_queue_unavailable"
_STATUS_EVENTS = {
    "installed": "plugin.installed",
    "enabled": "plugin.enabled",
    "disabled": "plugin.disabled",
    "failed": "plugin.failed",
}

_PLUGIN_STATUS_INSTALLED = "installed"
_PLUGIN_STATUS_ENABLED = "enabled"
_PLUGIN_STATUS_DISABLED = "disabled"
_PLUGIN_STATUS_FAILED = "failed"
_PLUGIN_STATUSES = {
    _PLUGIN_STATUS_INSTALLED,
    _PLUGIN_STATUS_ENABLED,
    _PLUGIN_STATUS_DISABLED,
    _PLUGIN_STATUS_FAILED,
    "uninstalled",
}


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_status(value: Any) -> str | None:
    text = _normalize_text(value).lower()
    return text or None


def _coerce_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    text = _normalize_text(value).lower()
    if not text:
        return None
    if text in {"1", "true", "yes", "y"}:
        return True
    if text in {"0", "false", "no", "n"}:
        return False
    return None


def lifecycle_event_id(plugin_id: uuid.UUID, event_type: str, updated_at: datetime) -> str:
    """Deterministic per-transition event ID: request path and sweep agree on it."""
    return str(uuid.uuid5(plugin_id, f"{event_type}:{updated_at.isoformat()}"))


def plugin_event_payload(
    plugin,
    *,
    requested_by_user_id: str | None,
    status_override: str | None = None,
    enabled_override: bool | None = None,
    failure_reason_override: str | None = None,
) -> dict[str, Any]:
    status_value = status_override or _normalize_text(plugin.status)
    enabled_value = plugin.enabled if enabled_override is None else enabled_override
    failure_reason = failure_reason_override if failure_reason_override is not None else plugin.failure_reason
    return {
        "plugin_id": str(plugin.plugin_id),
        "plugin_key": _normalize_text(plugin.plugin_key),
        "name": _normalize_text(plugin.name),
        "version": _normalize_text(plugin.version),
        "status": status_value,
        "enabled": bool(enabled_value),
        "signature_status": "declared_unverified",
        "dependency_status": "declared_unverified",
        "sandbox_status": "not_executed",
        "failure_reason": _normalize_text(failure_reason) or None,
        "requested_by_user_id": requested_by_user_id,
    }


async def _publish(redis, *, event_type: str, payload: dict[str, Any], correlation_id: Any,
                   event_id: str | None = None) -> str:
    # ADR-028 C20: the shared request-id -> UUID mapping; the original id is kept.
    correlation, extra = normalize_audit_correlation(correlation_id, None)
    return await publish_event(redis=redis, event_type=event_type, source="plugin",
                               payload={**payload, **extra}, correlation_id=str(correlation), event_id=event_id)


async def republish_deferred_plugin_events(*, db: AsyncSession, redis, limit: int = 50,
                                           grace_seconds: float = 30) -> int:
    """Republish committed-but-unpublished lifecycle events (the ``deferred`` rows).

    Rows are locked ``SKIP LOCKED`` and aged past ``grace_seconds`` so an in-flight
    request's own publication is not raced. The event ID is derived from the same
    committed transition, so a publication that actually reached Redis before its
    acknowledgement was lost is deduplicated by consumers. The requesting actor is
    not persisted on registry rows; republished payloads carry
    ``requested_by_user_id=null`` and ``delivery="deferred_republish"``.
    """
    repo = PluginRepository(db)
    published = 0
    for plugin in await repo.claim_deferred(limit=limit, older_than_seconds=grace_seconds):
        event_type = _STATUS_EVENTS.get(_normalize_status(plugin.status) or "")
        if event_type is None:
            continue
        payload = {**plugin_event_payload(plugin, requested_by_user_id=None), "delivery": "deferred_republish"}
        try:
            stream_entry_id = await _publish(redis, event_type=event_type, payload=payload,
                correlation_id=uuid.uuid5(plugin.plugin_id, "plugin-deferred-republish"),
                event_id=lifecycle_event_id(plugin.plugin_id, event_type, plugin.updated_at))
        except Exception as exc:  # noqa: BLE001 - stays deferred for the next sweep
            logger.warning("plugin_deferred_event_republish_failed", plugin_id=str(plugin.plugin_id),
                           event_type=event_type, error_type=type(exc).__name__)
            break
        plugin.queue_status, plugin.stream_entry_id, plugin.warning = "queued", stream_entry_id, None
        published += 1
    await db.commit()
    return published


class PluginService:
    """List, validate, and transition plugin registry records."""

    def __init__(self, *, db: AsyncSession, redis: aioredis.Redis | None):
        self._db = db
        self._redis = redis
        self._repo = PluginRepository(db)

    async def _assert_membership(
        self, *, user_id: str, claim_org_id: uuid.UUID | None, claim_workspace_id: uuid.UUID | None,
    ) -> None:
        # The plugin registry is platform-wide, not a tenant-owned resource.
        if claim_workspace_id is not None:
            await WorkspaceService(db=self._db, redis=self._redis).get_active_workspace(
                claim_workspace_id, user_id=user_id, claim_org_id=claim_org_id,
            )
        elif claim_org_id is not None:
            try:
                await OrgService(db=self._db, redis=self._redis).get_org(org_id=claim_org_id, user_id=user_id)
            except HTTPException as exc:
                # C6 masks "absent" and "not a member" as 404; for this platform-wide
                # registry a claimed org the caller cannot use is an authorization failure.
                if exc.status_code == status.HTTP_404_NOT_FOUND:
                    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                        detail="Insufficient permissions.") from exc
                raise
        else:
            orgs = await OrgService(db=self._db, redis=self._redis).list_orgs(user_id=user_id, page=1, page_size=1)
            if not orgs.items:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")

    async def list_plugins(
        self,
        *,
        status_filter: str | None,
        enabled_filter: str | None,
        search_filter: str | None,
        limit: int,
        actor_user_id: str,
        claim_org_id: uuid.UUID | None = None,
        claim_workspace_id: uuid.UUID | None = None,
    ) -> PluginListResponse:
        await self._assert_membership(
            user_id=actor_user_id, claim_org_id=claim_org_id, claim_workspace_id=claim_workspace_id,
        )
        normalized_status = _normalize_status(status_filter)
        if normalized_status is not None and normalized_status not in _PLUGIN_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "PLUGIN_STATUS_INVALID",
                    "message": "status must be one of: installed, enabled, disabled, failed, uninstalled.",
                },
            )

        normalized_enabled = _coerce_bool(enabled_filter)
        if enabled_filter is not None and normalized_enabled is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "PLUGIN_ENABLED_FILTER_INVALID",
                    "message": "enabled must be a boolean value.",
                },
            )

        normalized_search = _normalize_text(search_filter) or None
        bounded_limit = max(1, min(limit, 500))

        rows = await self._repo.list_plugins(
            status=normalized_status,
            enabled=normalized_enabled,
            search=normalized_search,
            limit=bounded_limit,
        )

        status_counts = {
            _PLUGIN_STATUS_INSTALLED: 0,
            _PLUGIN_STATUS_ENABLED: 0,
            _PLUGIN_STATUS_DISABLED: 0,
            _PLUGIN_STATUS_FAILED: 0,
            "uninstalled": 0,
        }
        items: list[PluginRecordResponse] = []
        for row in rows:
            row_status = _normalize_status(row.status) or _PLUGIN_STATUS_INSTALLED
            if row_status in status_counts:
                status_counts[row_status] += 1
            items.append(PluginRecordResponse.model_validate(row))

        return PluginListResponse(items=items, total=len(items), status_counts=status_counts)

    async def install_plugin(
        self,
        *,
        req: PluginInstallRequest,
        correlation_id: str,
        requested_by_user_id: str,
        claim_org_id: uuid.UUID | None = None,
        claim_workspace_id: uuid.UUID | None = None,
    ) -> PluginActionResponse:
        await self._assert_membership(
            user_id=requested_by_user_id, claim_org_id=claim_org_id, claim_workspace_id=claim_workspace_id,
        )
        plugin_key = _normalize_text(req.plugin_key).lower()
        manifest = req.model_dump(mode="json")
        existing = await self._repo.get_by_plugin_key(plugin_key)
        if existing is not None:
            if _normalize_text(existing.version) != req.version:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={"code": "PLUGIN_VERSION_CONFLICT",
                            "message": "plugin_key is already registered with a different version."},
                )
            if self._canonical_manifest(existing.manifest) != self._canonical_manifest(manifest):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={"code": "PLUGIN_MANIFEST_CONFLICT",
                            "message": "plugin_key/version is already registered with different declarations."},
                )
            if existing.status != "uninstalled":
                return self._serialize_action_response(
                    existing,
                    queue_status="replayed",
                    stream_entry_id=None,
                    warning=None,
                    idempotent_replay=True,
                )

        failure = (self._check_declared_signature(signer=req.signer, signature=req.signature)
                   or self._validate_dependencies(req.dependencies)
                   or self._validate_sandbox(req.sandbox))
        if failure is not None:
            await self._publish_plugin_failed_without_record(
                plugin_key=plugin_key,
                name=req.name,
                version=req.version,
                failure_code=failure["code"],
                failure_message=failure["message"],
                requested_by_user_id=requested_by_user_id,
                correlation_id=correlation_id,
            )
            raise HTTPException(
                status_code=failure["status_code"],
                detail={"code": failure["code"], "message": failure["message"]},
            )

        if existing is not None:
            plugin = existing
        else:
            plugin = await self._repo.create(
                plugin_id=uuid.uuid4(),
                plugin_key=plugin_key,
                name=_normalize_text(req.name),
                version=_normalize_text(req.version),
                manifest=manifest,
                signature_status="declared_unverified",
                dependency_status="declared_unverified",
                sandbox_status="not_executed",
                status=_PLUGIN_STATUS_INSTALLED,
                enabled=False,
                failure_reason=None,
                queue_status=_DEFERRED,
                stream_entry_id=None,
                warning=_QUEUE_UNAVAILABLE,
            )

        queue_status, stream_entry_id, warning = await self._transition_and_publish(
            plugin, status_value=_PLUGIN_STATUS_INSTALLED, enabled=False, failure_reason=None,
            event_type="plugin.installed", correlation_id=correlation_id,
            requested_by_user_id=requested_by_user_id,
        )
        return self._serialize_action_response(
            plugin,
            queue_status=queue_status,
            stream_entry_id=stream_entry_id,
            warning=warning,
            idempotent_replay=False,
        )

    async def enable_plugin(
        self,
        *,
        plugin_id: uuid.UUID,
        correlation_id: str,
        requested_by_user_id: str,
        claim_org_id: uuid.UUID | None = None,
        claim_workspace_id: uuid.UUID | None = None,
    ) -> PluginActionResponse:
        await self._assert_membership(
            user_id=requested_by_user_id, claim_org_id=claim_org_id, claim_workspace_id=claim_workspace_id,
        )
        plugin = await self._repo.get_by_id(plugin_id)
        if plugin is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "PLUGIN_NOT_FOUND", "message": "Plugin not found."},
            )

        self._assert_installed(plugin)
        if plugin.enabled and _normalize_status(plugin.status) == _PLUGIN_STATUS_ENABLED:
            return self._serialize_action_response(
                plugin,
                queue_status="replayed",
                stream_entry_id=None,
                warning=None,
                idempotent_replay=True,
            )

        manifest = plugin.manifest if isinstance(plugin.manifest, dict) else {}
        schema_failure = None
        try:
            PluginInstallRequest.model_validate(manifest)
        except ValidationError:
            schema_failure = {"status_code": 400, "code": "PLUGIN_MANIFEST_INVALID",
                              "message": "Stored declarations do not satisfy the registry schema."}

        signature_failure = self._check_declared_signature(
            signer=_normalize_text(manifest.get("signer")),
            signature=_normalize_text(manifest.get("signature")),
        )
        dependency_failure = self._validate_dependencies(manifest.get("dependencies"))
        sandbox_failure = self._validate_sandbox(manifest.get("sandbox"))

        failure = schema_failure or signature_failure or dependency_failure or sandbox_failure
        if failure is not None:
            await self._transition_and_publish(
                plugin, status_value=_PLUGIN_STATUS_FAILED, enabled=False, failure_reason=failure["code"],
                event_type="plugin.failed", correlation_id=correlation_id,
                requested_by_user_id=requested_by_user_id,
            )
            raise HTTPException(
                status_code=failure["status_code"],
                detail={
                    "code": failure["code"],
                    "message": failure["message"],
                },
            )

        queue_status, stream_entry_id, warning = await self._transition_and_publish(
            plugin, status_value=_PLUGIN_STATUS_ENABLED, enabled=True, failure_reason=None,
            event_type="plugin.enabled", correlation_id=correlation_id,
            requested_by_user_id=requested_by_user_id,
        )
        return self._serialize_action_response(
            plugin,
            queue_status=queue_status,
            stream_entry_id=stream_entry_id,
            warning=warning,
            idempotent_replay=False,
        )

    async def disable_plugin(
        self,
        *,
        plugin_id: uuid.UUID,
        correlation_id: str,
        requested_by_user_id: str,
        claim_org_id: uuid.UUID | None = None,
        claim_workspace_id: uuid.UUID | None = None,
    ) -> PluginActionResponse:
        await self._assert_membership(
            user_id=requested_by_user_id, claim_org_id=claim_org_id, claim_workspace_id=claim_workspace_id,
        )
        plugin = await self._repo.get_by_id(plugin_id)
        if plugin is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "PLUGIN_NOT_FOUND", "message": "Plugin not found."},
            )

        self._assert_installed(plugin)
        if not plugin.enabled and _normalize_status(plugin.status) == _PLUGIN_STATUS_DISABLED:
            return self._serialize_action_response(
                plugin,
                queue_status="replayed",
                stream_entry_id=None,
                warning=None,
                idempotent_replay=True,
            )

        queue_status, stream_entry_id, warning = await self._transition_and_publish(
            plugin, status_value=_PLUGIN_STATUS_DISABLED, enabled=False, failure_reason=None,
            event_type="plugin.disabled", correlation_id=correlation_id,
            requested_by_user_id=requested_by_user_id,
        )
        return self._serialize_action_response(
            plugin,
            queue_status=queue_status,
            stream_entry_id=stream_entry_id,
            warning=warning,
            idempotent_replay=False,
        )

    async def uninstall_plugin(
        self, *, plugin_id: uuid.UUID, correlation_id: str, requested_by_user_id: str,
        claim_org_id: uuid.UUID | None = None, claim_workspace_id: uuid.UUID | None = None,
    ) -> None:
        await self._assert_membership(
            user_id=requested_by_user_id, claim_org_id=claim_org_id, claim_workspace_id=claim_workspace_id,
        )
        plugin = await self._repo.get_by_id(plugin_id)
        if plugin is None:
            raise HTTPException(status_code=404, detail={"code": "PLUGIN_NOT_FOUND", "message": "Plugin not found."})
        if plugin.status == "uninstalled":
            return
        previous_status = plugin.status
        await self._repo.update_lifecycle(
            plugin, status="uninstalled", enabled=False, failure_reason=plugin.failure_reason,
            queue_status="not_applicable", stream_entry_id=None, warning=None,
        )
        # The Identity boundary normalizes the request id (ADR-028 C20) and keeps
        # the original client identifier in the audit metadata.
        await append_audit_log(
            db=self._db, event_type="plugin.registry.removed", actor_id=uuid.UUID(requested_by_user_id),
            resource_type="plugin", resource_id=plugin.plugin_id,
            correlation_id=correlation_id,
            metadata={"registry_only": True, "previous_status": previous_status, "status": "uninstalled"},
        )
        await self._db.commit()

    async def _transition_and_publish(
        self,
        plugin,
        *,
        status_value: str,
        enabled: bool,
        failure_reason: str | None,
        event_type: str,
        correlation_id: str,
        requested_by_user_id: str,
    ) -> tuple[str, str | None, str | None]:
        """ADR-028: commit the transition (pessimistically ``deferred``), then publish.

        Only a successful publication is recorded, and only if no later transition
        has been committed meanwhile, so a slow publisher can never resurrect or
        relabel a concurrently changed record.
        """
        await self._repo.update_lifecycle(
            plugin, status=status_value, enabled=enabled, failure_reason=failure_reason,
            queue_status=_DEFERRED, stream_entry_id=None, warning=_QUEUE_UNAVAILABLE,
        )
        await self._db.commit()
        await self._db.refresh(plugin)
        committed_at = plugin.updated_at
        queue_status, stream_entry_id, warning = await self._publish_lifecycle_event(
            event_type=event_type,
            correlation_id=correlation_id,
            payload=plugin_event_payload(plugin, requested_by_user_id=requested_by_user_id),
            event_id=lifecycle_event_id(plugin.plugin_id, event_type, committed_at),
        )
        if queue_status == "queued":
            await self._repo.mark_published(plugin.plugin_id, committed_at=committed_at,
                                            stream_entry_id=stream_entry_id)
            await self._db.commit()
            await self._db.refresh(plugin)
        return queue_status, stream_entry_id, warning

    @staticmethod
    def _assert_installed(plugin) -> None:
        if plugin.status == "uninstalled":
            raise HTTPException(status_code=409, detail={
                "code": "PLUGIN_UNINSTALLED", "message": "Explicit identical-manifest reinstall is required.",
            })

    @staticmethod
    def _canonical_manifest(manifest: dict) -> str | None:
        # JSON encoding preserves type distinctions (true != 1); only object order is ignored.
        try:
            normalized = PluginInstallRequest.model_validate(manifest).model_dump(mode="json")
            return canonical_json_bytes(normalized).decode("ascii")
        except ValidationError:
            return None

    @staticmethod
    def _parse_csv_settings(value: str) -> set[str]:
        return {item.strip().lower() for item in value.split(",") if item.strip()}

    def _check_declared_signature(self, *, signer: str, signature: str) -> dict[str, Any] | None:
        """Admission of a *declared* signer/signature (format + allowlist only).

        Nothing is cryptographically verified: a prefix/length check proves nothing
        about authenticity, which is why every record reports
        ``signature_status="declared_unverified"``. The error code is unchanged for
        compatibility; its messages state the declaration-only semantics.
        """
        settings = get_settings()
        trusted_signers = self._parse_csv_settings(settings.PLUGIN_TRUSTED_SIGNERS)
        normalized_signer = signer.strip().lower()
        if not normalized_signer or normalized_signer not in trusted_signers:
            return {
                "status_code": status.HTTP_400_BAD_REQUEST,
                "code": "PLUGIN_SIGNATURE_INVALID",
                "message": "Declared signer is not on the registry admission allowlist (signer identity is never verified).",
            }

        normalized_signature = signature.strip()
        if not normalized_signature.startswith(settings.PLUGIN_SIGNATURE_PREFIX):
            return {
                "status_code": status.HTTP_400_BAD_REQUEST,
                "code": "PLUGIN_SIGNATURE_INVALID",
                "message": "Declared signature format is invalid; cryptographic verification is unsupported.",
            }

        if len(normalized_signature) < settings.PLUGIN_SIGNATURE_MIN_LENGTH:
            return {
                "status_code": status.HTTP_400_BAD_REQUEST,
                "code": "PLUGIN_SIGNATURE_INVALID",
                "message": "Declared signature is shorter than the admission format minimum; it is not verified.",
            }

        return None

    def _validate_dependencies(self, dependencies: Any) -> dict[str, Any] | None:
        settings = get_settings()
        deps = dependencies if isinstance(dependencies, dict) else {}

        if any(key in deps and not isinstance(deps[key], str) for key in ("platform_version", "requires_platform")):
            return {"status_code": 400, "code": "PLUGIN_DEPENDENCY_INVALID",
                    "message": "Declared platform versions must be strings."}

        required_platform = _normalize_text(
            deps.get("platform_version") or deps.get("requires_platform")
        )
        if required_platform and required_platform != settings.PLUGIN_PLATFORM_VERSION:
            return {
                "status_code": status.HTTP_409_CONFLICT,
                "code": "PLUGIN_DEPENDENCY_INCOMPATIBLE",
                "message": "Declared platform version does not match the registry configuration.",
            }

        requires_raw = deps.get("requires", [])
        if requires_raw is None:
            requires_raw = []
        if not isinstance(requires_raw, list):
            return {
                "status_code": status.HTTP_400_BAD_REQUEST,
                "code": "PLUGIN_DEPENDENCY_INVALID",
                "message": "Plugin requires must be a list when provided.",
            }

        if (len(requires_raw) > settings.PLUGIN_MAX_DEPENDENCY_COUNT
                or any(not isinstance(item, str) or not item.strip() for item in requires_raw)):
            return {
                "status_code": status.HTTP_400_BAD_REQUEST,
                "code": "PLUGIN_DEPENDENCY_INVALID",
                "message": "Dependencies must be nonempty strings within the configured count limit.",
            }

        return None

    def _validate_sandbox(self, sandbox: Any) -> dict[str, Any] | None:
        settings = get_settings()
        sandbox_data = sandbox if isinstance(sandbox, dict) else {}
        if "isolation_mode" in sandbox_data and not isinstance(sandbox_data["isolation_mode"], str):
            return {"status_code": 400, "code": "PLUGIN_SANDBOX_INVALID",
                    "message": "Declared isolation_mode must be a string."}
        isolation_mode = _normalize_text(sandbox_data.get("isolation_mode") or "process").lower()
        allowed_modes = self._parse_csv_settings(settings.PLUGIN_ALLOWED_ISOLATION_MODES)
        if isolation_mode not in allowed_modes:
            return {
                "status_code": status.HTTP_400_BAD_REQUEST,
                "code": "PLUGIN_SANDBOX_INVALID",
                "message": "Plugin isolation mode is not allowed.",
            }

        permissions_raw = sandbox_data.get("permissions", [])
        if permissions_raw is None:
            permissions_raw = []
        if (not isinstance(permissions_raw, list)
                or any(not isinstance(item, str) or not item.strip() for item in permissions_raw)):
            return {
                "status_code": status.HTTP_400_BAD_REQUEST,
                "code": "PLUGIN_SANDBOX_INVALID",
                "message": "Plugin sandbox permissions must be a list.",
            }

        requested_permissions = {
            _normalize_text(item).lower() for item in permissions_raw if _normalize_text(item)
        }
        allowed_permissions = self._parse_csv_settings(settings.PLUGIN_ALLOWED_PERMISSIONS)
        if not requested_permissions.issubset(allowed_permissions):
            return {
                "status_code": status.HTTP_403_FORBIDDEN,
                "code": "PLUGIN_PERMISSION_SCOPE_INVALID",
                "message": "Declared permissions exceed the registry admission allowlist; no runtime enforcement exists.",
            }

        return None

    async def _admit_rejection_event(self, *, plugin_key: str, failure_code: str, requested_by_user_id: str) -> bool:
        """Rate-limit ``plugin.failed`` events for rejected installs (no record exists).

        An identical rejection (actor, key, code) is published at most once per
        window, and each actor at most ``PLUGIN_FAILED_EVENT_MAX_PER_ACTOR`` times per
        window, so repeated invalid submissions cannot flood the stream/audit log.
        """
        settings = get_settings()
        window = max(1, int(getattr(settings, "PLUGIN_FAILED_EVENT_WINDOW_SECONDS", 60)))
        per_actor = max(1, int(getattr(settings, "PLUGIN_FAILED_EVENT_MAX_PER_ACTOR", 10)))
        fingerprint = canonical_sha256({"actor": requested_by_user_id, "code": failure_code, "key": plugin_key})
        actor_key = f"plugin:failed-event:actor:{canonical_sha256(requested_by_user_id)[:32]}"
        try:
            if not await self._redis.set(f"plugin:failed-event:{fingerprint[:32]}", "1", nx=True, ex=window):
                return False
            await self._redis.set(actor_key, 0, nx=True, ex=window)
            count = int(await self._redis.incr(actor_key))
            if await self._redis.ttl(actor_key) == -1:
                await self._redis.expire(actor_key, window)
            return count <= per_actor
        except Exception:  # noqa: BLE001 - without Redis the event cannot be published anyway
            return False

    async def _publish_plugin_failed_without_record(
        self,
        *,
        plugin_key: str,
        name: str,
        version: str,
        failure_code: str,
        failure_message: str,
        requested_by_user_id: str,
        correlation_id: str,
    ) -> None:
        if self._redis is None or not await self._admit_rejection_event(
            plugin_key=plugin_key, failure_code=failure_code, requested_by_user_id=requested_by_user_id,
        ):
            logger.info("plugin_rejection_event_suppressed", failure_code=failure_code)
            return
        payload = {
            "plugin_id": None,
            "plugin_key": plugin_key,
            "name": _normalize_text(name),
            "version": _normalize_text(version),
            "status": _PLUGIN_STATUS_FAILED,
            "enabled": False,
            "signature_status": "declared_unverified",
            "dependency_status": "declared_unverified",
            "sandbox_status": "not_executed",
            "failure_reason": failure_code,
            "failure_message": failure_message,
            "requested_by_user_id": requested_by_user_id,
        }
        await self._publish_lifecycle_event(
            event_type="plugin.failed",
            correlation_id=correlation_id,
            payload=payload,
        )

    async def _publish_lifecycle_event(
        self,
        *,
        event_type: str,
        correlation_id: str,
        payload: dict[str, Any],
        event_id: str | None = None,
    ) -> tuple[str, str | None, str | None]:
        """Best-effort publication after commit; never raises."""
        if self._redis is None:
            return _DEFERRED, None, _QUEUE_UNAVAILABLE
        try:
            stream_entry_id = await _publish(self._redis, event_type=event_type, payload=payload,
                                             correlation_id=correlation_id, event_id=event_id)
            return "queued", stream_entry_id, None
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "plugin_lifecycle_event_publish_failed",
                event_type=event_type,
                error=str(exc),
            )
            return _DEFERRED, None, _QUEUE_UNAVAILABLE

    @staticmethod
    def _serialize_action_response(
        plugin,
        *,
        queue_status: str,
        stream_entry_id: str | None,
        warning: str | None,
        idempotent_replay: bool,
    ) -> PluginActionResponse:
        payload = PluginRecordResponse.model_validate(plugin).model_dump()
        payload.update(
            {
                "queue_status": queue_status,
                "stream_entry_id": stream_entry_id,
                "warning": warning,
                "idempotent_replay": idempotent_replay,
            }
        )
        return PluginActionResponse.model_validate(payload)

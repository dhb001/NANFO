"""NANFO Backend - Plugin module repository.

Persistence operations for plugin lifecycle records.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import String, cast, desc, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.plugin.models import PluginRecord


class PluginRepository:
    """Repository for plugin registry persistence."""

    def __init__(self, db: AsyncSession):
        self._db = db

    @staticmethod
    def _apply_filters(
        query,
        *,
        status: str | None,
        enabled: bool | None,
        search: str | None,
    ):
        if status is not None:
            query = query.where(PluginRecord.status == status)
        else:
            query = query.where(PluginRecord.status != "uninstalled")
        if enabled is not None:
            query = query.where(PluginRecord.enabled == enabled)
        if search:
            normalized = search.strip()
            if normalized:
                pattern = f"%{normalized}%"
                query = query.where(
                    or_(
                        PluginRecord.plugin_key.ilike(pattern),
                        PluginRecord.name.ilike(pattern),
                        PluginRecord.version.ilike(pattern),
                        cast(PluginRecord.manifest, String).ilike(pattern),
                    )
                )
        return query

    async def list_plugins(
        self,
        *,
        status: str | None,
        enabled: bool | None,
        search: str | None,
        limit: int,
    ) -> list[PluginRecord]:
        query = select(PluginRecord)
        query = self._apply_filters(
            query,
            status=status,
            enabled=enabled,
            search=search,
        )
        query = query.order_by(desc(PluginRecord.updated_at), desc(PluginRecord.installed_at)).limit(limit)
        result = await self._db.execute(query)
        return list(result.scalars().all())

    async def get_by_id(self, plugin_id: uuid.UUID) -> PluginRecord | None:
        result = await self._db.execute(
            select(PluginRecord).where(PluginRecord.plugin_id == plugin_id).with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def get_by_plugin_key(self, plugin_key: str) -> PluginRecord | None:
        # Lock even an absent key; the unique constraint remains the final safeguard.
        await self._db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"plugin-registry:{plugin_key}"},
        )
        result = await self._db.execute(
            select(PluginRecord).where(PluginRecord.plugin_key == plugin_key).with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        plugin_id: uuid.UUID,
        plugin_key: str,
        name: str,
        version: str,
        manifest: dict,
        signature_status: str,
        dependency_status: str,
        sandbox_status: str,
        status: str,
        enabled: bool,
        failure_reason: str | None,
        queue_status: str,
        stream_entry_id: str | None,
        warning: str | None,
    ) -> PluginRecord:
        plugin = PluginRecord(
            plugin_id=plugin_id,
            plugin_key=plugin_key,
            name=name,
            version=version,
            manifest=manifest,
            signature_status=signature_status,
            dependency_status=dependency_status,
            sandbox_status=sandbox_status,
            status=status,
            enabled=enabled,
            failure_reason=failure_reason,
            queue_status=queue_status,
            stream_entry_id=stream_entry_id,
            warning=warning,
        )
        self._db.add(plugin)
        await self._db.flush()
        return plugin

    async def update_lifecycle(
        self,
        plugin: PluginRecord,
        *,
        status: str,
        enabled: bool,
        failure_reason: str | None,
        queue_status: str,
        stream_entry_id: str | None,
        warning: str | None,
        signature_status: str | None = None,
        dependency_status: str | None = None,
        sandbox_status: str | None = None,
        manifest: dict | None = None,
        version: str | None = None,
    ) -> PluginRecord:
        if status == "uninstalled" and plugin.status != "uninstalled":
            plugin.uninstalled_at = datetime.now(UTC)
        elif status == "installed":
            plugin.uninstalled_at = None
        plugin.status = status
        plugin.enabled = enabled
        plugin.failure_reason = failure_reason
        plugin.queue_status = queue_status
        plugin.stream_entry_id = stream_entry_id
        plugin.warning = warning
        if signature_status is not None:
            plugin.signature_status = signature_status
        if dependency_status is not None:
            plugin.dependency_status = dependency_status
        if sandbox_status is not None:
            plugin.sandbox_status = sandbox_status
        if manifest is not None:
            plugin.manifest = manifest
        if version is not None:
            plugin.version = version
        await self._db.flush()
        return plugin

    async def mark_published(self, plugin_id: uuid.UUID, *, committed_at: datetime,
                             stream_entry_id: str | None) -> bool:
        """Record a publication only for the exact committed transition it describes.

        A concurrent later transition (for example uninstall) changes ``updated_at``;
        the late publisher then leaves that newer state untouched.
        """
        marked = await self._db.scalar(
            update(PluginRecord)
            .where(PluginRecord.plugin_id == plugin_id, PluginRecord.updated_at == committed_at,
                   PluginRecord.queue_status == "deferred")
            .values(queue_status="queued", stream_entry_id=stream_entry_id, warning=None)
            .returning(PluginRecord.plugin_id)
        )
        return marked is not None

    async def claim_deferred(self, *, limit: int, older_than_seconds: float) -> list[PluginRecord]:
        """Deferred lifecycle rows past the in-flight grace period, locked for the sweep."""
        result = await self._db.execute(
            select(PluginRecord)
            .where(PluginRecord.queue_status == "deferred", PluginRecord.stream_entry_id.is_(None),
                   PluginRecord.updated_at < func.now() - timedelta(seconds=older_than_seconds))
            .order_by(PluginRecord.updated_at, PluginRecord.plugin_id)
            .with_for_update(skip_locked=True)
            .limit(limit)
        )
        return list(result.scalars().all())

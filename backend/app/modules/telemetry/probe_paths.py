"""ADR018 selected-probe read composition owned by Telemetry (no capture/control).

The router stays thin: this service performs the Network-owned access check, loads
the operator binding and re-validates it through Network's public
``EmulationDiscoveryService`` contract (validation only, never the graph-mutating
``apply_snapshot``), then replays probe evidence with ``ProbePathsReader``.
``build_emulation_discovery`` delegates to Network's single public composition
(``app.modules.network.emulation.build_emulation_discovery``): public owner services
only, bound devices read with ``NetworkService.get_devices_for_owner``, no Network
repository constructed here (ADR-028).
"""

from __future__ import annotations

import uuid
from pathlib import Path

import redis.asyncio as aioredis
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.network.emulation import EmulationDiscoveryService, load_binding
from app.modules.network.emulation import build_emulation_discovery as _network_emulation_discovery
from app.modules.network.service import NetworkService
from app.modules.telemetry.emulation import SnapshotReader
from app.modules.telemetry.paths import ProbePathsReader, ProbePathsResponse


def build_emulation_discovery(db: AsyncSession, redis: aioredis.Redis | None, *, topology=None,
                              expected_topology: dict) -> EmulationDiscoveryService:
    """Network's public binding-validation contract for one fresh session.

    Kept as Telemetry's public entry point; the composition itself is Network-owned.
    """
    return _network_emulation_discovery(db, redis, expected_topology=expected_topology, topology=topology)


class ProbePathsService:
    def __init__(self, *, db: AsyncSession, redis: aioredis.Redis | None, settings):
        self._db, self._redis, self._settings = db, redis, settings

    async def read(
        self,
        *,
        network_id: uuid.UUID,
        actor_user_id: str,
        requested_workspace_id: uuid.UUID | None,
        claim_org_id: uuid.UUID | None,
    ) -> ProbePathsResponse:
        settings = self._settings
        network = await NetworkService(self._db, self._redis).assert_network_workspace_access(
            network_id=network_id, requested_workspace_id=requested_workspace_id,
            actor_user_id=actor_user_id, claim_org_id=claim_org_id,
        )
        result = ProbePathsResponse(network_id=network.network_id, workspace_id=network.workspace_id,
                                    status="unavailable")
        if (settings.EXECUTION_MODE != "emulation" or not settings.EMULATION_SNAPSHOT_PATH
                or not settings.EMULATION_BINDING_PATH):
            return result.model_copy(update={"reason": "probe_provider_not_configured"})
        try:
            from emulation.topology import manifest
        except ImportError:
            return result.model_copy(update={"reason": "probe_provider_not_installed"})

        snapshot_path = Path(settings.EMULATION_SNAPSHOT_PATH)
        try:
            binding = await load_binding(Path(settings.EMULATION_BINDING_PATH), snapshot_path=snapshot_path)
            if binding.network_id != network.network_id or binding.workspace_id != network.workspace_id:
                return result.model_copy(update={"reason": "binding_scope_mismatch"})
            # Current owner capabilities, writable membership and active device ownership.
            await build_emulation_discovery(self._db, self._redis,
                                            expected_topology=manifest()).validate_binding(binding)
        except (OSError, ValueError, HTTPException):
            return result.model_copy(update={"reason": "trusted_binding_unavailable"})
        return await ProbePathsReader(SnapshotReader(
            snapshot_path, max_bytes=settings.EMULATION_SNAPSHOT_MAX_BYTES,
            max_age_seconds=settings.EMULATION_SNAPSHOT_MAX_AGE_SECONDS,
            future_skew_seconds=settings.EMULATION_SNAPSHOT_FUTURE_SKEW_SECONDS,
        )).read(binding=binding, network_id=network.network_id, workspace_id=network.workspace_id)

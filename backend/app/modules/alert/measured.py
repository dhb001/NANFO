"""Alert public persisted-telemetry ingestion contract (ADR019).

The event is a locator, never measurement evidence. Re-read the owning Telemetry
public query contract and current Network binding/Identity/Organization authority.
"""

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.alert.detector import (
    METRICS, DetectorSettings, MeasuredObservation, advance_window, detector_identity, identity_key,
)
from app.modules.alert.repository import AlertRepository
from app.modules.identity.service import AuthService
from app.modules.network.emulation import load_binding
from app.modules.network.service import DeviceService, NetworkService
from app.modules.organization.service import WorkspaceService
from app.modules.telemetry.service import TelemetryQueryService


class MeasuredAlertService:
    def __init__(self, *, db, redis=None, rules=None, clock=None):
        self.db, self.redis = db, redis
        self.repo = AlertRepository(db)
        self.rules = rules or DetectorSettings()
        self.clock = clock or (lambda: datetime.now(UTC))

    async def ingest_persisted_event(self, event: dict) -> None:
        if event.get("event_type") != "telemetry.metric.ingested":
            return
        try:
            candidate = MeasuredObservation.model_validate({**event["payload"],
                "event_id": event["event_id"], "correlation_id": event["correlation_id"]})
        except (ValidationError, KeyError, TypeError):
            return
        # Exact-time bounded lookup through Telemetry's public service, not its repository.
        history = await TelemetryQueryService(self.db).get_device_history(
            device_id=candidate.device_id, network_id=candidate.network_id,
            workspace_id=candidate.workspace_id, metric=candidate.metric, page=1, page_size=500,
            start_time=candidate.observed_at, end_time=candidate.observed_at + timedelta(microseconds=1),
        )
        persisted = next((item for item in history.items if item.event_id == candidate.event_id), None)
        if persisted is None:
            return
        try:
            observation = MeasuredObservation.model_validate(persisted.model_dump())
        except ValidationError:
            return
        try:
            org_id = await self.authorize_observation(observation)
        except (HTTPException, ValueError):
            return
        await self.apply_observation(observation, org_id)

    async def authorize_observation(self, observation, *, fresh=False):
        if fresh:
            # A new identity map and READ COMMITTED transaction cannot reuse
            # membership/user objects loaded before a contended detector lock.
            async with AsyncSession(bind=self.db.bind, expire_on_commit=False) as db:
                return await MeasuredAlertService(db=db, redis=self.redis).authorize_observation(observation)
        settings = get_settings()
        if (settings.EXECUTION_MODE != "emulation" or not settings.EMULATION_BINDING_PATH
                or not settings.EMULATION_SNAPSHOT_PATH):
            raise ValueError("measured observer binding unavailable")
        binding = await load_binding(Path(settings.EMULATION_BINDING_PATH),
                                     snapshot_path=Path(settings.EMULATION_SNAPSHOT_PATH))
        if (binding.network_id != observation.network_id or binding.workspace_id != observation.workspace_id
                or binding.topology_id != observation.tags.topology_id):
            raise ValueError("observation outside binding scope")
        tags = observation.tags
        if tags.port_no is not None:
            if (binding.switches.get(tags.dpid) != observation.device_id
                    or f"{tags.dpid}:{tags.port_no}" not in binding.port_capacities_mbps):
                raise ValueError("observation outside bound port")
            if (observation.metric == "link_utilization_percent"
                    and tags.capacity_mbps != binding.port_capacities_mbps[f"{tags.dpid}:{tags.port_no}"]):
                raise ValueError("capacity differs from operator binding")
        elif (observation.device_id not in binding.hosts.values() or tags.peer_host not in binding.hosts
              or binding.hosts[tags.peer_host] == observation.device_id):
            raise ValueError("observation outside bound probe")
        actor = str(binding.actor_user_id)
        profile = await AuthService(self.db, self.redis).get_profile(actor)
        if not {"read:telemetry", "read:topology", "write:config"}.issubset(profile.permissions):
            raise ValueError("observer capability revoked")
        network = NetworkService(self.db, self.redis)
        await network.assert_network_workspace_access(network_id=observation.network_id,
            requested_workspace_id=observation.workspace_id, actor_user_id=actor, require_write=True)
        actual_network, _ = await network.assert_device_workspace_access(device_id=observation.device_id,
            requested_workspace_id=observation.workspace_id, actor_user_id=actor)
        if actual_network != observation.network_id:
            raise ValueError("device moved from observed network")
        needed = {observation.device_id}
        if tags.peer_host is not None:
            needed.add(binding.hosts[tags.peer_host])
        devices, page = DeviceService(self.db, self.redis), 1
        while needed:
            result = await devices.list_devices(network_id=observation.network_id, actor_user_id=actor,
                requested_workspace_id=observation.workspace_id, page=page, page_size=500)
            needed.difference_update(device.device_id for device in result.items if device.status == "active")
            if page * 500 >= result.total or not result.items:
                break
            page += 1
        if needed:
            raise ValueError("observed device or peer is inactive")
        workspace = await WorkspaceService(self.db, self.redis).get_active_workspace(
            observation.workspace_id, user_id=actor, require_write=True)
        return workspace.org_id

    async def apply_observation(self, observation, org_id):
        """Internal transaction boundary; caller has verified persisted evidence and authority."""
        rule = getattr(self.rules, METRICS[observation.metric][0])
        now = self.clock()
        if not 0 <= (now - observation.observed_at).total_seconds() <= rule.max_age_seconds:
            return
        identity = detector_identity(observation, org_id, rule)
        key = identity_key(identity)
        state = await self.repo.lock_detector(key, identity, rule.model_dump())
        if state.rule != rule.model_dump():
            raise ValueError("operator rule changed without a new version")
        incident = await self.repo.get_by_id(state.incident_id, lock=True) if state.incident_id else None
        try:
            authorized_org = await self.authorize_observation(observation, fresh=True)
        except (HTTPException, ValueError):
            await self.db.rollback()
            return
        now = self.clock()
        if authorized_org != org_id or not 0 <= (now - observation.observed_at).total_seconds() <= rule.max_age_seconds:
            await self.db.rollback()
            return
        if not await self.repo.accept_observation(observation, key):
            await self.db.commit()
            return
        ready = advance_window(state, observation, rule, now=now)
        if incident is not None and incident.status == "resolved":
            state.incident_id = None
            state.phase, state.phase_since, state.sample_count = None, None, 0
            ready = False
            incident = None
        payload = {**identity, "detector_key": key, "rule": rule.model_dump(),
            "synthetic": False, "execution_mode": "emulation", "quality": "measured",
            "observation_event_id": str(observation.event_id), "observed_at": observation.observed_at.isoformat(),
            "value": observation.value, "unit": observation.unit,
            "measurement_method": observation.tags.measurement_method,
            "sample_count": state.sample_count,
            "window_started_at": state.phase_since.isoformat() if state.phase_since else None}
        if ready and state.phase == "breach" and incident is None:
            alert_id, event_id = uuid.uuid4(), uuid.uuid4()
            payload.update(alert_id=str(alert_id), alert_key=f"measured:{key}", status="active", severity="warning")
            incident = await self.repo.create_generated(alert_id=alert_id, alert_key=payload["alert_key"],
                source="telemetry", severity="warning", correlation_id=observation.correlation_id,
                payload=payload, generated_event_id=event_id, created_at=now, detector_key=key)
            state.incident_id = incident.alert_id
            await self.repo.append_history(alert_id=alert_id, event_type="alert.generated",
                correlation_id=observation.correlation_id, occurred_at=now, payload=payload,
                event_id=event_id, publish=True)
        elif ready and state.phase == "recovery" and incident is not None:
            event_id = uuid.uuid4()
            payload = {**incident.payload, **payload, "status": "resolved", "resolution_reason": "measured_recovery",
                       "resolved_at": now.isoformat()}
            await self.repo.mark_resolved(incident, resolved_by_user_id=None, resolved_at=now,
                                          payload=payload, resolved_event_id=event_id)
            await self.repo.append_history(alert_id=incident.alert_id, event_type="alert.resolved",
                correlation_id=observation.correlation_id, occurred_at=now, payload=payload,
                event_id=event_id, publish=True)
            state.incident_id = None
            state.phase, state.phase_since, state.sample_count = None, None, 0
        try:
            authorized_org = await self.authorize_observation(observation, fresh=True)
        except (HTTPException, ValueError):
            await self.db.rollback()
            return
        now = self.clock()
        if authorized_org != org_id or not 0 <= (now - observation.observed_at).total_seconds() <= rule.max_age_seconds:
            await self.db.rollback()
            return
        await self.db.commit()

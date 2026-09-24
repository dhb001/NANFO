"""Alert public persisted-telemetry ingestion contract (ADR019).

The event is a locator, never measurement evidence. Re-read the owning Telemetry
public query contract and current Network binding/Identity/Organization authority.

ADR-028: the operator binding is cached briefly per binding-file revision and the
pre-lock authority answer per (revision, actor, scope) for a few seconds. The
authoritative decision is one fresh-session authorization immediately before each
commit, so revocation or expiry still rolls back observation/state/history/outbox.
"""

import json
import os
import threading
import time
import uuid
from collections import OrderedDict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.correlation import correlation_uuid
from app.modules.alert.detector import (
    METRICS, DetectorSettings, MeasuredObservation, advance_window, detector_identity, identity_key,
)
from app.modules.alert.repository import AlertRepository
from app.modules.identity.service import AuthService
from app.modules.network.emulation import load_binding
from app.modules.network.service import DeviceService, NetworkService
from app.modules.organization.service import WorkspaceService
from app.modules.telemetry.service import TelemetryQueryService
from app.modules.telemetry.pins import EvidenceOwnerScope, TelemetryEvidenceService
from app.modules.telemetry.references import (
    OwnerReferenceItem, OwnerReferencePage, evidence_item, install_direct_owner,
    install_owner_guard, page_position, reference_page,
)
from app.modules.alert.models import AlertHistory, AlertRecord

install_direct_owner("alert")

# Binding reads are cached per file revision; pre-lock authority per (revision,
# actor, scope). Short TTLs bound staleness; commits always re-authorize freshly.
BINDING_CACHE_SECONDS = 5.0
AUTHORITY_CACHE_SECONDS = 5.0
_AUTHORITY_CACHE_MAX = 1024
_cache_lock = threading.Lock()
_binding_cache: dict[tuple, tuple[float, object]] = {}
_authority_cache: "OrderedDict[tuple, tuple[float, uuid.UUID]]" = OrderedDict()


def _binding_revision(path: Path, snapshot_path: Path) -> tuple | None:
    """File identity of the operator binding; None when it cannot be observed."""
    try:
        info = os.stat(path, follow_symlinks=False)
    except (OSError, ValueError):
        return None
    return (str(path), str(snapshot_path), info.st_dev, info.st_ino, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


async def _cached_binding(path: Path, snapshot_path: Path):
    """Return ``(binding, revision)``; the revision keys every dependent cache entry."""
    revision = _binding_revision(path, snapshot_path)
    if revision is not None:
        with _cache_lock:
            hit = _binding_cache.get(revision)
        if hit is not None and time.monotonic() - hit[0] <= BINDING_CACHE_SECONDS:
            return hit[1], revision
    loaded_at = time.monotonic()
    binding = await load_binding(path, snapshot_path=snapshot_path)
    # Cache only when the file did not change while it was read and validated.
    if revision is not None and _binding_revision(path, snapshot_path) == revision:
        with _cache_lock:
            _binding_cache.clear()
            _binding_cache[revision] = (loaded_at, binding)
        return binding, revision
    return binding, None


def _authority_cache_get(key: tuple) -> uuid.UUID | None:
    with _cache_lock:
        hit = _authority_cache.get(key)
        if hit is None:
            return None
        if time.monotonic() - hit[0] > AUTHORITY_CACHE_SECONDS:
            _authority_cache.pop(key, None)
            return None
        return hit[1]


def _authority_cache_put(key: tuple, org_id: uuid.UUID) -> None:
    with _cache_lock:
        _authority_cache[key] = (time.monotonic(), org_id)
        _authority_cache.move_to_end(key)
        while len(_authority_cache) > _AUTHORITY_CACHE_MAX:
            _authority_cache.popitem(last=False)


def clear_authority_caches() -> None:
    """Drop cached bindings/authority (tests and operator binding rotation)."""
    with _cache_lock:
        _binding_cache.clear()
        _authority_cache.clear()


def alert_scope(row):
    payload = row.payload or {}
    return payload.get("scope") if isinstance(payload.get("scope"), dict) else payload


def alert_telemetry_references(row):
    identity = row.alert_id if isinstance(row, AlertRecord) else row.event_id
    if identity is None:
        identity = uuid.uuid4()
        if isinstance(row, AlertRecord):
            row.alert_id = identity
        else:
            row.event_id = identity
    return evidence_item(identity=f"alert:{identity}", network_id=alert_scope(row).get("network_id"),
                         fields={"payload": row.payload})


for _model in (AlertRecord, AlertHistory):
    install_owner_guard(_model, owner="alert", extractor=alert_telemetry_references,
        workspace=lambda row: alert_scope(row).get("workspace_id"), fields=("payload",))


async def telemetry_reference_page(db, *, workspace_id, after=None, limit=100):
    """Alert-owned observation receipt enumeration, never just current incidents.

    Platform-scoped (runtime SLO) alerts are no tenant's evidence and are not
    enumerated for any workspace: they record no workspace, and the before-flush
    owner guard refuses unscoped known telemetry identities, so they can never
    reference tenant telemetry (otherwise every workspace would report them as
    ``legacy_alert_scope_unknown`` forever).
    """
    from sqlalchemy import func, or_, select
    from app.modules.alert.models import AlertDetectorState, AlertObservation
    from app.modules.alert.scope import PLATFORM_ALERT_SCOPE

    stage, last = page_position(after, stages=3, limit=limit)
    if stage:
        model, key = ((AlertRecord, AlertRecord.alert_id), (AlertHistory, AlertHistory.event_id))[stage - 1]
        direct = model.payload["workspace_id"].astext
        nested = model.payload["scope"]["workspace_id"].astext
        tenant_unscoped = (direct.is_(None) & nested.is_(None)
                           & (func.coalesce(model.payload["alert_scope"].astext, "") != PLATFORM_ALERT_SCOPE))
        query = select(model).where(or_(direct == str(workspace_id), nested == str(workspace_id), tenant_unscoped))
        if last:
            query = query.where(key > last)
        rows = list((await db.scalars(query.order_by(key).limit(limit + 1))).all())

        def historical(row):
            if not alert_scope(row).get("workspace_id"):
                return OwnerReferenceItem(identity=str(getattr(row, key.key)), unknown="legacy_alert_scope_unknown")
            if (row.payload or {}).get("observation_event_id"):
                # The permanent observation receipt was enumerated in stage0.
                # Legacy payloads without that receipt remain pre-enrollment only.
                item = alert_telemetry_references(row)
                item.unknown = "legacy_event_locator_retained"
                return item
            return alert_telemetry_references(row)

        return reference_page(rows, extractor=historical, key=lambda row: getattr(row, key.key),
                              limit=limit, stage=stage, stages=3)
    # Both tables belong to Alert. Observation receipts retain every window sample.
    query = select(AlertObservation, AlertDetectorState.identity).outerjoin(
        AlertDetectorState, AlertDetectorState.detector_key == AlertObservation.detector_key
    ).where(or_(AlertDetectorState.identity["workspace_id"].astext == str(workspace_id),
                AlertDetectorState.identity["workspace_id"].astext.is_(None)))
    if last:
        query = query.where(AlertObservation.event_id > last)
    rows = (await db.execute(query.order_by(AlertObservation.event_id).limit(limit + 1))).all()
    service = TelemetryEvidenceService(db, scope=EvidenceOwnerScope(owner="alert", workspace_id=workspace_id))
    items = []
    for row, identity in rows[:limit]:
        try:
            ref = await service.event_reference(event_id=row.event_id, network_id=uuid.UUID(identity["network_id"]),
                                                reference_id=row.event_id)
            items.append(OwnerReferenceItem(identity=str(row.event_id), references=[ref]))
        except (ValueError, KeyError, TypeError):
            items.append(OwnerReferenceItem(identity=str(row.event_id), unknown="legacy_alert_observation_unavailable"))
    return OwnerReferencePage(items=items, next_cursor=(
        json.dumps([0, str(rows[limit - 1][0].event_id)]) if len(rows) > limit else json.dumps([1, None])))


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
            # The event is only a locator; an opaque request id maps through the
            # shared deterministic helper (the persisted record's value is stored).
            candidate = MeasuredObservation.model_validate({**event["payload"],
                "event_id": event["event_id"], "correlation_id": correlation_uuid(event["correlation_id"])})
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
            # Pre-lock screen only (may be answered from the short authority cache);
            # apply_observation re-authorizes freshly before it commits anything.
            org_id = await self.authorize_observation(observation)
        except (HTTPException, ValueError):
            return
        await self.apply_observation(observation, org_id)

    async def authorize_observation(self, observation, *, fresh=False, use_cache=True):
        if fresh:
            # A new identity map and READ COMMITTED transaction cannot reuse
            # membership/user objects loaded before a contended detector lock.
            async with AsyncSession(bind=self.db.bind, expire_on_commit=False) as db:
                return await MeasuredAlertService(db=db, redis=self.redis).authorize_observation(
                    observation, use_cache=False)
        settings = get_settings()
        if (settings.EXECUTION_MODE != "emulation" or not settings.EMULATION_BINDING_PATH
                or not settings.EMULATION_SNAPSHOT_PATH):
            raise ValueError("measured observer binding unavailable")
        binding, revision = await _cached_binding(Path(settings.EMULATION_BINDING_PATH),
                                                  Path(settings.EMULATION_SNAPSHOT_PATH))
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
        needed = {observation.device_id}
        if tags.peer_host is not None:
            needed.add(binding.hosts[tags.peer_host])
        key = None if revision is None else (revision, actor, observation.network_id, observation.workspace_id,
                                             frozenset(needed))
        if use_cache and key is not None:
            cached = _authority_cache_get(key)
            if cached is not None:
                return cached
        org_id = await self._current_authority(observation, actor, needed)
        if key is not None:
            _authority_cache_put(key, org_id)
        return org_id

    async def _current_authority(self, observation, actor, needed):
        """Live Identity/Network/Organization authority of the binding actor."""
        profile = await AuthService(self.db, self.redis).get_profile(actor)
        if not {"read:telemetry", "read:topology", "write:config"}.issubset(profile.permissions):
            raise ValueError("observer capability revoked")
        network = NetworkService(self.db, self.redis)
        await network.assert_network_workspace_access(network_id=observation.network_id,
            requested_workspace_id=observation.workspace_id, actor_user_id=actor)
        actual_network, _ = await network.assert_device_workspace_access(device_id=observation.device_id,
            requested_workspace_id=observation.workspace_id, actor_user_id=actor)
        if actual_network != observation.network_id:
            raise ValueError("device moved from observed network")
        needed = set(needed)
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
        # Observation authority is a read, not an inventory mutation. Retaining
        # parent locks here can deadlock the subsequent fresh-session fences,
        # including when a revoker is queued behind the original transaction.
        workspace = await WorkspaceService(self.db, self.redis).check_workspace_write_authority(
            observation.workspace_id, user_id=actor)
        return workspace.org_id

    def _fresh(self, observation, rule) -> bool:
        return 0 <= (self.clock() - observation.observed_at).total_seconds() <= rule.max_age_seconds

    async def _commit_if_authorized(self, observation, org_id, rule) -> bool:
        """The single authoritative fence: fresh authority and wall clock, then commit."""
        try:
            authorized_org = await self.authorize_observation(observation, fresh=True)
        except (HTTPException, ValueError):
            await self.db.rollback()
            return False
        if authorized_org != org_id or not self._fresh(observation, rule):
            await self.db.rollback()
            return False
        await self.db.commit()
        return True

    async def apply_observation(self, observation, org_id):
        """Internal transaction boundary; caller has verified persisted evidence and authority."""
        rule = getattr(self.rules, METRICS[observation.metric][0])
        if not self._fresh(observation, rule):
            return
        identity = detector_identity(observation, org_id, rule)
        key = identity_key(identity)
        state = await self.repo.lock_detector(key, identity, rule.model_dump())
        if state.rule != rule.model_dump():
            raise ValueError("operator rule changed without a new version")
        incident = await self.repo.get_by_id(state.incident_id, lock=True) if state.incident_id else None
        # Cheap post-lock clock check; authority is re-verified once, before commit.
        now = self.clock()
        if not 0 <= (now - observation.observed_at).total_seconds() <= rule.max_age_seconds:
            await self.db.rollback()
            return
        evidence = TelemetryEvidenceService(self.db, scope=EvidenceOwnerScope(
            owner="alert", workspace_id=observation.workspace_id))
        reference = await evidence.event_reference(event_id=observation.event_id,
            network_id=observation.network_id, reference_id=observation.event_id)
        await evidence.pin(reference)
        if not await self.repo.accept_observation(observation, key):
            await self._commit_if_authorized(observation, org_id, rule)
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
        await self._commit_if_authorized(observation, org_id, rule)

"""NANFO Backend - Alert module repository.

Persistence operations for alert lifecycle records.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import (
    String, Text, and_, any_, bindparam, case, cast, delete, desc, func, not_, or_, select, text, union, union_all,
    update,
)
from sqlalchemy.dialects.postgresql import ARRAY, insert
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.events.publisher import publish_event
from app.modules.alert.models import AlertConsumedEvent, AlertDetectorState, AlertHistory, AlertObservation, AlertOutbox, AlertRecord
from app.modules.alert.scope import PLATFORM_ALERT_SCOPE, AlertListScope, scope_columns

MAX_SEARCH_LENGTH = 200
LIKE_ESCAPE = "\\"
# Operator-meaningful payload text fields searched besides key/source/correlation.
# The whole serialized payload is never searched (unbounded, unindexable, and it
# would match scope identifiers or evidence values by accident).
SEARCHABLE_PAYLOAD_FIELDS = (
    "message", "title", "metric", "device_id", "peer_host", "severity_reason",
    "runbook_playbook", "resolution_reason", "measurement_method",
)
_UUID_ARRAY = ARRAY(PG_UUID(as_uuid=True))
_TEXT_ARRAY = ARRAY(Text)


def escape_like(value: str) -> str:
    """Escape LIKE/ILIKE wildcards so user input always matches literally."""
    return value.replace(LIKE_ESCAPE, LIKE_ESCAPE * 2).replace("%", LIKE_ESCAPE + "%").replace("_", LIKE_ESCAPE + "_")


def _json_scope(key: str):
    return func.coalesce(AlertRecord.payload[key].astext, AlertRecord.payload["scope"][key].astext)


def _member_of(column, values, *, name: str, as_text: bool = False):
    """Set membership: ``column = :value`` for one value, else ``column = ANY(:values)``.

    Several values bind as ONE array parameter, so the statement text (and its
    prepared plan) does not depend on how many workspaces/networks/orgs a user
    has. A single value stays an equality so the ``(workspace_id, updated_at
    DESC, alert_id DESC)`` index also satisfies ORDER BY ... LIMIT.
    """
    values = sorted(str(value) for value in values) if as_text else sorted(values)
    if len(values) == 1:
        return column == values[0]
    return column == any_(bindparam(name, values, type_=_TEXT_ARRAY if as_text else _UUID_ARRAY, unique=True))


def _by_org(resource_orgs):
    """``{resource: org}`` -> ``{org: [resources]}`` in deterministic order."""
    grouped: dict = {}
    for resource, org in resource_orgs.items():
        grouped.setdefault(org, []).append(resource)
    return dict(sorted(grouped.items()))


def _paired(resource, org, resource_orgs, *, name: str, as_text: bool = False):
    """Rows of the given resources whose recorded org, if any, is that resource's org.

    One ``resource = ANY(:ids) AND (org IS NULL OR org = :org)`` clause per
    organization (a user belongs to few): exact pairing with array binds.
    """
    clauses = [
        and_(_member_of(resource, resources, name=name, as_text=as_text),
             or_(org.is_(None), org == (str(org_id) if as_text else org_id)))
        for org_id, resources in _by_org(resource_orgs).items()
    ]
    return clauses[0] if len(clauses) == 1 else or_(*clauses)


def _platform_marked():
    """Platform-scoped rows: ``alert_scope = 'platform'`` and no recorded workspace.

    Never NULL (safe to negate). Mirrors :func:`app.modules.alert.scope.is_platform_scoped`.
    """
    return and_(func.coalesce(AlertRecord.payload["alert_scope"].astext, "") == PLATFORM_ALERT_SCOPE,
                _json_scope("workspace_id").is_(None))


def _scope_branches(scope: AlertListScope):
    """(workspace-column branch, NULL-workspace branch); either may be None.

    Both reference only Alert-owned columns/JSON. The first is served by the
    ``(workspace_id, updated_at DESC, alert_id DESC)`` index; the second covers
    legacy network-only and org-only rows, rows with no tenancy columns and,
    for platform authority only, platform-scoped rows (never tenant-visible).
    """
    workspaces = dict(scope.workspace_orgs)
    workspace_branch = None
    if workspaces:
        workspace_branch = _paired(AlertRecord.workspace_id, AlertRecord.org_id, workspaces, name="workspace_ids")
        if scope.network_id is not None:
            workspace_branch = and_(workspace_branch, AlertRecord.network_id == scope.network_id)
    network_orgs = {network: workspaces[workspace] for network, workspace in scope.networks.items()
                    if workspace in workspaces and (scope.network_id is None or network == scope.network_id)}
    org_only = scope.member_org_ids if scope.network_id is None else frozenset()
    tenant = []
    if network_orgs:
        tenant.append(_paired(AlertRecord.network_id, AlertRecord.org_id, network_orgs, name="network_ids"))
    if org_only:
        tenant.append(and_(AlertRecord.network_id.is_(None), _member_of(AlertRecord.org_id, org_only, name="org_ids")))
    fallback = _json_fallback(workspaces, network_orgs, org_only, scope.network_id)
    if fallback is not None:
        tenant.append(and_(AlertRecord.network_id.is_(None), AlertRecord.org_id.is_(None), fallback))
    parts = []
    if tenant:
        # Platform-scoped rows are never tenant-visible, whatever else they record.
        parts.append(and_(not_(_platform_marked()), or_(*tenant)))
    if scope.platform and scope.network_id is None:
        parts.append(_platform_marked())
    null_branch = and_(AlertRecord.workspace_id.is_(None), or_(*parts)) if parts else None
    return workspace_branch, null_branch


def _json_fallback(workspaces, network_orgs, org_only, selected_network):
    """Historical JSON predicate, only for rows without any tenancy column."""
    workspace, network, org = _json_scope("workspace_id"), _json_scope("network_id"), _json_scope("org_id")
    parts = []
    if workspaces:
        rows = _paired(workspace, org, workspaces, name="json_workspace_ids", as_text=True)
        if selected_network is not None:
            rows = and_(rows, network == str(selected_network))
        parts.append(rows)
    if network_orgs:
        parts.append(and_(workspace.is_(None),
                          _paired(network, org, network_orgs, name="json_network_ids", as_text=True)))
    if org_only:
        parts.append(and_(workspace.is_(None), network.is_(None),
                          _member_of(org, org_only, name="json_org_ids", as_text=True)))
    return or_(*parts) if parts else None


def _filters(*, status, severity, source, correlation_id, search, created_from=None, created_before=None):
    clauses = []
    if status is not None:
        clauses.append(AlertRecord.status == status)
    if severity is not None:
        clauses.append(AlertRecord.severity == severity)
    if source is not None:
        clauses.append(AlertRecord.source == source)
    if correlation_id is not None:
        clauses.append(AlertRecord.correlation_id == correlation_id)
    if created_from is not None:
        clauses.append(AlertRecord.created_at >= created_from)
    if created_before is not None:
        clauses.append(AlertRecord.created_at < created_before)
    normalized = (search or "").strip()
    if normalized:
        if len(normalized) > MAX_SEARCH_LENGTH:
            raise ValueError("search exceeds the maximum length")
        pattern = f"%{escape_like(normalized)}%"
        fields = [AlertRecord.alert_key, AlertRecord.source, cast(AlertRecord.correlation_id, String),
                  *(AlertRecord.payload[key].astext for key in SEARCHABLE_PAYLOAD_FIELDS)]
        clauses.append(or_(*(field.ilike(pattern, escape=LIKE_ESCAPE) for field in fields)))
    return clauses


class AlertRepository:
    """Repository for alert lifecycle persistence."""

    def __init__(self, db: AsyncSession):
        self._db = db

    async def list_alerts(
        self,
        *,
        status: str | None,
        severity: str | None,
        source: str | None,
        correlation_id: uuid.UUID | None,
        search: str | None,
        limit: int,
        scope: AlertListScope,
        created_from: datetime | None = None,
        created_before: datetime | None = None,
    ) -> list[AlertRecord]:
        """Scope and content predicates run before ORDER/LIMIT on Alert-owned data."""
        branches = [branch for branch in _scope_branches(scope) if branch is not None]
        if not branches:
            return []
        filters = _filters(status=status, severity=severity, source=source, correlation_id=correlation_id,
                           search=search, created_from=created_from, created_before=created_before)
        order = (desc(AlertRecord.updated_at), desc(AlertRecord.alert_id))
        pages = [select(AlertRecord).where(branch, *filters).order_by(*order).limit(limit) for branch in branches]
        if len(pages) == 1:
            query = pages[0]
        else:
            # Each branch is an ordered, limited (index-servable) scan; merge them.
            page = union_all(*pages).subquery("alert_page")
            row = aliased(AlertRecord, page)
            query = select(row).order_by(desc(row.updated_at), desc(row.alert_id)).limit(limit)
        result = await self._db.execute(query)
        return list(result.scalars().all())

    async def count_alerts(
        self,
        *,
        status: str | None,
        severity: str | None,
        source: str | None,
        correlation_id: uuid.UUID | None,
        search: str | None,
        scope: AlertListScope,
        created_from: datetime | None = None,
        created_before: datetime | None = None,
    ) -> dict[str, int]:
        """Exact per-status counts of every match (same predicates, no LIMIT)."""
        branches = [branch for branch in _scope_branches(scope) if branch is not None]
        if not branches:
            return {}
        filters = _filters(status=status, severity=severity, source=source, correlation_id=correlation_id,
                           search=search, created_from=created_from, created_before=created_before)
        query = (select(AlertRecord.status, func.count()).where(or_(*branches), *filters)
                 .group_by(AlertRecord.status))
        counts: dict[str, int] = {}
        for status_value, count in (await self._db.execute(query)).all():
            counts[status_value] = int(count)
        return counts

    async def legacy_network_ids(self, *, limit: int) -> list[uuid.UUID]:
        """Distinct networks recorded without a workspace (Alert-owned data only).

        Covers backfilled network-only rows and column-less rows whose JSON scope
        names only a network. Invalid identifiers are ignored (they fail closed);
        platform-scoped rows are never tenant-visible, so they are not probed.
        """
        network = _json_scope("network_id")
        tenant = not_(_platform_marked())
        columns = select(cast(AlertRecord.network_id, String).label("network_id")).where(
            AlertRecord.workspace_id.is_(None), AlertRecord.network_id.is_not(None), tenant)
        fallback = select(network.label("network_id")).where(
            AlertRecord.workspace_id.is_(None), AlertRecord.network_id.is_(None), AlertRecord.org_id.is_(None),
            _json_scope("workspace_id").is_(None), network.is_not(None), tenant)
        distinct = union(columns, fallback).subquery("legacy_networks")
        values = (await self._db.execute(select(distinct.c.network_id).limit(limit))).scalars().all()
        parsed = set()
        for value in values:
            try:
                parsed.add(uuid.UUID(str(value)))
            except (TypeError, ValueError, AttributeError):
                continue
        return sorted(parsed)

    @staticmethod
    def _stamp_scope(alert: AlertRecord, payload: dict) -> None:
        # Tenancy columns are an indexed projection of the recorded payload scope.
        for key, value in scope_columns(payload).items():
            setattr(alert, key, value)

    async def get_by_id(self, alert_id: uuid.UUID, *, lock: bool = False) -> AlertRecord | None:
        query = select(AlertRecord).where(AlertRecord.alert_id == alert_id).execution_options(populate_existing=True)
        result = await self._db.execute(query.with_for_update() if lock else query)
        return result.scalar_one_or_none()

    async def get_by_generated_event_id(self, event_id: uuid.UUID) -> AlertRecord | None:
        result = await self._db.execute(
            select(AlertRecord).where(AlertRecord.generated_event_id == event_id)
        )
        return result.scalar_one_or_none()

    async def get_latest_unresolved_by_key(self, alert_key: str, *, identity: dict) -> AlertRecord | None:
        predicates = []
        for key, value in identity.items():
            if key == "rule":
                from sqlalchemy.dialects.postgresql import JSONB
                expression = cast(func.coalesce(
                    func.nullif(AlertRecord.payload[key], text("'null'::jsonb")),
                    func.nullif(AlertRecord.payload["scope"][key], text("'null'::jsonb"))), JSONB)
                predicates.append(expression.is_(None) if value is None else expression == value)
            else:
                expression = func.coalesce(AlertRecord.payload[key].astext, AlertRecord.payload["scope"][key].astext)
                if key.endswith("_id") and key != "run_id":
                    expression = func.lower(expression)
                predicates.append(expression.is_(None) if value is None else expression == str(value))
        result = await self._db.execute(
            select(AlertRecord)
            .where(
                AlertRecord.alert_key == alert_key,
                AlertRecord.status != "resolved",
                AlertRecord.detector_key.is_(None),
                *predicates,
            )
            .order_by(desc(AlertRecord.updated_at), desc(AlertRecord.created_at))
            .limit(1)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def lock_legacy_identity(self, identity_key: str) -> None:
        await self._db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                               {"key": "alert:legacy:" + identity_key})

    async def consume_generation(self, event_id: uuid.UUID, payload_sha256: str) -> bool:
        inserted = await self._db.execute(insert(AlertConsumedEvent).values(
            event_id=event_id, payload_sha256=payload_sha256,
        ).on_conflict_do_nothing(index_elements=["event_id"]).returning(AlertConsumedEvent.event_id))
        # Identical and conflicting replays have the same no-op result. Never
        # replace first-delivery evidence or expose another tenant's incident.
        return inserted.scalar_one_or_none() is not None

    async def link_consumed_generation(self, event_id: uuid.UUID, alert_id: uuid.UUID) -> None:
        await self._db.execute(update(AlertConsumedEvent).where(
            AlertConsumedEvent.event_id == event_id, AlertConsumedEvent.alert_id.is_(None),
        ).values(alert_id=alert_id))

    async def create_generated(
        self,
        *,
        alert_id: uuid.UUID,
        alert_key: str,
        source: str,
        severity: str | None,
        correlation_id: uuid.UUID,
        payload: dict,
        generated_event_id: uuid.UUID | None,
        created_at: datetime,
        detector_key: str | None = None,
    ) -> AlertRecord:
        alert = AlertRecord(
            alert_id=alert_id,
            alert_key=alert_key,
            detector_key=detector_key,
            source=source,
            status="active",
            severity=severity,
            correlation_id=correlation_id,
            payload=payload,
            generated_event_id=generated_event_id,
            created_at=created_at,
            updated_at=created_at,
        )
        self._stamp_scope(alert, payload)
        self._db.add(alert)
        await self._db.flush()
        return alert

    async def lock_detector(self, key: str, identity: dict, rule: dict) -> AlertDetectorState:
        await self._db.execute(insert(AlertDetectorState).values(
            detector_key=key, identity=identity, rule=rule, sample_count=0,
        ).on_conflict_do_nothing(index_elements=["detector_key"]))
        return (await self._db.execute(select(AlertDetectorState).where(
            AlertDetectorState.detector_key == key,
        ).with_for_update().execution_options(populate_existing=True))).scalar_one()

    async def accept_observation(self, observation, key: str) -> bool:
        return (await self._db.execute(insert(AlertObservation).values(
            event_id=observation.event_id, detector_key=key, observed_at=observation.observed_at,
        ).on_conflict_do_nothing().returning(AlertObservation.event_id))).scalar_one_or_none() is not None

    async def purge_observations(self, *, retention_days: int, batch_size: int) -> int:
        """Delete ONE bounded batch of observation receipts past retention; commits.

        A receipt is kept while it can still explain an incident:

        * its detector has an unresolved incident (open incident window);
        * it lies in the detector's current phase run (``observed_at >= phase_since``);
        * an incident lifecycle record names it (``alert_history`` payload
          ``observation_event_id``: the generating/resolving sample of any incident).

        Purging cannot cause double application: samples older than a rule's
        ``max_age_seconds`` (<= 300 s) are rejected as stale before deduplication.
        Telemetry pins taken when a sample was applied are not released here.
        No ORDER BY: the LIMIT stops the scan at the first ``batch_size`` eligible
        rows, and SKIP LOCKED lets concurrent purgers take disjoint batches.
        """
        if not 1 <= retention_days <= 36500 or not 1 <= batch_size <= 10000:
            raise ValueError("retention must be 1..36500 days and batch size 1..10000")
        state, incident = aliased(AlertDetectorState), aliased(AlertRecord)
        open_window = (
            select(text("1")).select_from(state)
            .outerjoin(incident, incident.alert_id == state.incident_id)
            .where(
                state.detector_key == AlertObservation.detector_key,
                or_(and_(incident.alert_id.is_not(None), incident.status != "resolved"),
                    and_(state.phase.is_not(None), state.phase_since.is_not(None),
                         AlertObservation.observed_at >= state.phase_since)),
            )
            .exists()
        )
        incident_evidence = (
            select(text("1"))
            .where(AlertHistory.payload["observation_event_id"].astext == cast(AlertObservation.event_id, String))
            .exists()
        )
        batch = (
            select(AlertObservation.event_id)
            .where(AlertObservation.observed_at < func.now() - timedelta(days=retention_days),
                   ~open_window, ~incident_evidence)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
        result = await self._db.execute(
            delete(AlertObservation).where(AlertObservation.event_id.in_(batch))
            .returning(AlertObservation.event_id))
        deleted = len(result.all())
        await self._db.commit()
        return deleted

    async def append_history(self, *, alert_id, event_type, correlation_id, occurred_at,
                             payload, event_id=None, publish=False):
        event_id = event_id or uuid.uuid4()
        inserted = (await self._db.execute(insert(AlertHistory).values(
            event_id=event_id, alert_id=alert_id, event_type=event_type,
            correlation_id=correlation_id, occurred_at=occurred_at, payload=payload,
        ).on_conflict_do_nothing().returning(AlertHistory.event_id))).scalar_one_or_none()
        if inserted is not None and publish:
            self._db.add(AlertOutbox(event_id=event_id))
        return event_id

    async def history(self, alert_id):
        return list((await self._db.execute(select(AlertHistory).where(
            AlertHistory.alert_id == alert_id,
        ).order_by(AlertHistory.occurred_at, AlertHistory.event_id))).scalars().all())

    async def publish_one(self, redis) -> bool:
        # A short row lock plus bounded Redis I/O makes crash/retry safe without a lease daemon.
        import asyncio

        # Serialize the tiny publication path so multiple workers cannot send a
        # resolution ahead of its generation/acknowledgement.
        if not (await self._db.execute(text("SELECT pg_try_advisory_xact_lock(190018)"))).scalar_one():
            return False
        row = (await self._db.execute(select(AlertOutbox).join(
            AlertHistory, AlertHistory.event_id == AlertOutbox.event_id,
        ).where(
            AlertOutbox.published_at.is_(None),
        ).order_by(AlertHistory.alert_id, case(
            (AlertHistory.event_type == "alert.generated", 0),
            (AlertHistory.event_type == "alert.acknowledged", 1), else_=2), AlertOutbox.event_id).limit(1)
          .with_for_update(of=AlertOutbox, skip_locked=True))).scalar_one_or_none()
        if row is None:
            return False
        history = await self._db.get(AlertHistory, row.event_id)
        async with asyncio.timeout(5):
            await publish_event(redis=redis, event_type=history.event_type, source="alert",
                                payload=history.payload, correlation_id=str(history.correlation_id),
                                event_id=str(history.event_id))
        row.published_at = datetime.now(UTC)
        await self._db.commit()
        return True

    async def mark_acknowledged(
        self,
        alert: AlertRecord,
        *,
        acknowledged_by_user_id: str | None,
        acknowledged_at: datetime,
        payload: dict,
        acknowledged_event_id: uuid.UUID | None,
    ) -> AlertRecord:
        alert.status = "acknowledged"
        alert.acknowledged_by_user_id = acknowledged_by_user_id
        alert.acknowledged_at = acknowledged_at
        alert.payload = payload
        self._stamp_scope(alert, payload)
        if acknowledged_event_id is not None:
            alert.acknowledged_event_id = acknowledged_event_id
        await self._db.flush()
        return alert

    async def mark_resolved(
        self,
        alert: AlertRecord,
        *,
        resolved_by_user_id: str | None,
        resolved_at: datetime,
        payload: dict,
        resolved_event_id: uuid.UUID | None,
    ) -> AlertRecord:
        alert.status = "resolved"
        alert.resolved_by_user_id = resolved_by_user_id
        alert.resolved_at = resolved_at
        alert.payload = payload
        self._stamp_scope(alert, payload)
        if resolved_event_id is not None:
            alert.resolved_event_id = resolved_event_id
        await self._db.flush()
        return alert

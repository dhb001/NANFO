"""NANFO Backend - Alert module repository.

Persistence operations for alert lifecycle records.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import String, and_, case, cast, desc, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.events.publisher import publish_event
from app.modules.alert.models import AlertConsumedEvent, AlertDetectorState, AlertHistory, AlertObservation, AlertOutbox, AlertRecord


class AlertRepository:
    """Repository for alert lifecycle persistence."""

    def __init__(self, db: AsyncSession):
        self._db = db

    @staticmethod
    def _apply_filters(
        query,
        *,
        status: str | None,
        severity: str | None,
        source: str | None,
        correlation_id: uuid.UUID | None,
        search: str | None,
    ):
        if status is not None:
            query = query.where(AlertRecord.status == status)
        if severity is not None:
            query = query.where(AlertRecord.severity == severity)
        if source is not None:
            query = query.where(AlertRecord.source == source)
        if correlation_id is not None:
            query = query.where(AlertRecord.correlation_id == correlation_id)
        if search:
            normalized = search.strip()
            if normalized:
                pattern = f"%{normalized}%"
                query = query.where(
                    or_(
                        AlertRecord.alert_key.ilike(pattern),
                        AlertRecord.source.ilike(pattern),
                        cast(AlertRecord.correlation_id, String).ilike(pattern),
                        cast(AlertRecord.payload, String).ilike(pattern),
                    )
                )
        return query

    async def list_alerts(
        self,
        *,
        status: str | None,
        severity: str | None,
        source: str | None,
        correlation_id: uuid.UUID | None,
        search: str | None,
        limit: int,
        scopes: list[tuple[uuid.UUID, uuid.UUID, list[uuid.UUID]]] | None = None,
        org_ids: list[uuid.UUID] | None = None,
        network_id: uuid.UUID | None = None,
    ) -> list[AlertRecord]:
        query = select(AlertRecord)
        # Scope predicates reference only Alert-owned JSON, before ORDER/LIMIT.
        workspace = func.coalesce(AlertRecord.payload["workspace_id"].astext, AlertRecord.payload["scope"]["workspace_id"].astext)
        network = func.coalesce(AlertRecord.payload["network_id"].astext, AlertRecord.payload["scope"]["network_id"].astext)
        org = func.coalesce(AlertRecord.payload["org_id"].astext, AlertRecord.payload["scope"]["org_id"].astext)
        allowed = [and_(workspace.is_(None), network.is_(None), org.in_([str(i) for i in org_ids or []]))]
        for ws_id, org_id, network_ids in scopes or []:
            allowed.append(and_(
                or_(workspace == str(ws_id), and_(workspace.is_(None), network.in_([str(i) for i in network_ids]))),
                or_(network.is_(None), network.in_([str(i) for i in network_ids])),
                or_(org.is_(None), org == str(org_id)),
            ))
        query = query.where(or_(*allowed))
        if network_id is not None:
            query = query.where(network == str(network_id))
        query = self._apply_filters(
            query,
            status=status,
            severity=severity,
            source=source,
            correlation_id=correlation_id,
            search=search,
        )
        query = query.order_by(
            desc(AlertRecord.updated_at), desc(AlertRecord.created_at), desc(AlertRecord.alert_id),
        ).limit(limit)
        result = await self._db.execute(query)
        return list(result.scalars().all())

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
        if resolved_event_id is not None:
            alert.resolved_event_id = resolved_event_id
        await self._db.flush()
        return alert

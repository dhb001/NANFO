"""Telemetry ingestion scaffold service.

VS2 Step 5 scope:
- Collector lifecycle contract
- Payload normalization
- Internal event publish path only (no persistence)
"""

from __future__ import annotations

import asyncio
import uuid
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.events.publisher import publish_event
from app.modules.telemetry.counters import TelemetryHealthCounterService
from app.modules.telemetry.repository import TelemetryRecordRepository
from app.modules.telemetry.schemas import (
    TelemetryDeviceHistoryResponse,
    TelemetryHealthResponse,
    TelemetryHistoryResponse,
    TelemetryRecordResponse,
)

logger = get_logger(__name__)

_RUNTIME_SUSTAINED_FAILURE_DEFAULT_THRESHOLD = 3
_RUNTIME_SUSTAINED_FAILURE_ACTIVATED_EVENT_TYPE = "telemetry.collector.sustained_failure_activated"
_RUNTIME_SUSTAINED_FAILURE_RECOVERED_EVENT_TYPE = "telemetry.collector.sustained_failure_recovered"


def compute_bounded_backoff_seconds(
    attempt: int,
    *,
    base_backoff_seconds: float,
    max_backoff_seconds: float,
) -> float:
    """Return a bounded exponential backoff delay for a 1-based attempt index."""
    if attempt < 1:
        return 0.0

    base = max(base_backoff_seconds, 0.0)
    cap = max(max_backoff_seconds, base)
    delay = base * (2 ** (attempt - 1))
    return min(delay, cap)


class TelemetryCollector(ABC):
    """Lifecycle interface for telemetry collectors."""

    @abstractmethod
    async def start(self) -> None:
        pass

    @abstractmethod
    async def stop(self) -> None:
        pass


class RuntimeTelemetryAdapter(ABC):
    """Runtime adapter interface for production telemetry poll actions."""

    @abstractmethod
    async def poll(self) -> list[dict[str, Any]]:
        """Collect a batch of raw telemetry samples from the runtime adapter."""


class ProductionTelemetryAdapterStub(RuntimeTelemetryAdapter):
    """Minimal production adapter stub for runtime poll-action wiring.

    Returns an empty batch by default so startup/runtime wiring is production-shaped
    without introducing vendor-specific SNMP/gRPC implementation yet.
    """

    async def poll(self) -> list[dict[str, Any]]:
        return []


def _is_runtime_sample_minimally_valid(raw: dict[str, Any]) -> bool:
    required_ids = ("device_id", "network_id", "workspace_id")
    if any(not str(raw.get(field, "")).strip() for field in required_ids):
        return False
    if not str(raw.get("metric", "")).strip():
        return False
    return raw.get("value") is not None


async def _safe_runtime_adapter_counter_update(
    update: Callable[[], Awaitable[int]],
    *,
    adapter_name: str,
    counter_name: str,
) -> None:
    try:
        await update()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "telemetry_runtime_adapter_counter_update_failed",
            adapter=adapter_name,
            counter_name=counter_name,
            error=str(exc),
        )


def build_runtime_poll_action(
    *,
    collector_runner: TelemetryCollectorRunner,
    adapter: RuntimeTelemetryAdapter,
) -> Callable[[], Awaitable[None]]:
    """Build the runtime poll action that uses a production-shaped adapter."""

    async def _poll_action() -> None:
        adapter_name = adapter.__class__.__name__
        try:
            samples = await adapter.poll()
        except Exception as exc:
            logger.warning(
                "telemetry_runtime_adapter_poll_failed",
                adapter=adapter_name,
                error=str(exc),
            )
            raise

        if not isinstance(samples, list):
            logger.warning(
                "telemetry_runtime_adapter_batch_invalid",
                adapter=adapter_name,
                batch_type=type(samples).__name__,
            )
            return

        batch_size = len(samples)
        await _safe_runtime_adapter_counter_update(
            lambda: collector_runner.counter_service.set_runtime_adapter_last_batch_size(batch_size),
            adapter_name=adapter_name,
            counter_name="runtime_adapter_last_batch_size",
        )

        for sample in samples:
            if not isinstance(sample, dict):
                await _safe_runtime_adapter_counter_update(
                    collector_runner.counter_service.increment_runtime_adapter_invalid_sample,
                    adapter_name=adapter_name,
                    counter_name="runtime_adapter_invalid_samples",
                )
                logger.warning(
                    "telemetry_runtime_adapter_sample_invalid",
                    adapter=adapter_name,
                    reason="sample_not_object",
                    sample_type=type(sample).__name__,
                )
                continue

            if not _is_runtime_sample_minimally_valid(sample):
                await _safe_runtime_adapter_counter_update(
                    collector_runner.counter_service.increment_runtime_adapter_invalid_sample,
                    adapter_name=adapter_name,
                    counter_name="runtime_adapter_invalid_samples",
                )
                logger.warning(
                    "telemetry_runtime_adapter_sample_invalid",
                    adapter=adapter_name,
                    reason="missing_required_fields",
                )
                continue

            correlation_id = str(uuid.uuid4())
            await _safe_runtime_adapter_counter_update(
                collector_runner.counter_service.increment_runtime_adapter_ingest_attempt,
                adapter_name=adapter_name,
                counter_name="runtime_adapter_ingest_attempts",
            )
            try:
                await collector_runner.ingest_once(raw=sample, correlation_id=correlation_id)
            except Exception as exc:
                await _safe_runtime_adapter_counter_update(
                    collector_runner.counter_service.increment_runtime_adapter_ingest_failure,
                    adapter_name=adapter_name,
                    counter_name="runtime_adapter_ingest_failures",
                )
                logger.warning(
                    "telemetry_runtime_adapter_ingest_failed",
                    adapter=adapter_name,
                    correlation_id=correlation_id,
                    error=str(exc),
                )
                raise

    return _poll_action


class TelemetryIngestionService:
    """Normalize and publish telemetry ingestion events to internal bus."""

    def __init__(
        self,
        redis: aioredis.Redis,
        counter_service: TelemetryHealthCounterService | None = None,
    ):
        self._redis = redis
        self._counter_service = counter_service or TelemetryHealthCounterService(redis)

    @property
    def counter_service(self) -> TelemetryHealthCounterService:
        return self._counter_service

    @property
    def redis(self) -> aioredis.Redis:
        return self._redis

    def normalize_payload(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Normalize vendor-specific telemetry into canonical internal shape."""
        observed_at = raw.get("observed_at")
        if not observed_at:
            observed_at = datetime.now(UTC).isoformat()

        value_raw = raw.get("value", 0)
        try:
            value = float(value_raw)
        except (TypeError, ValueError):
            value = 0.0

        tags_raw = raw.get("tags")
        tags = tags_raw if isinstance(tags_raw, dict) else {}

        return {
            "device_id": str(raw.get("device_id", "")),
            "network_id": str(raw.get("network_id", "")),
            "workspace_id": str(raw.get("workspace_id", "")),
            "metric": str(raw.get("metric", "")),
            "value": value,
            "unit": str(raw.get("unit", "")),
            "observed_at": observed_at,
            "source": str(raw.get("source", "collector")),
            "tags": tags,
        }

    async def ingest(self, raw: dict[str, Any], correlation_id: str) -> str:
        payload = self.normalize_payload(raw)
        entry_id = await publish_event(
            redis=self._redis,
            event_type="telemetry.metric.ingested",
            source="telemetry",
            payload=payload,
            correlation_id=correlation_id,
        )
        await self._increment_ingested_counter(correlation_id=correlation_id)
        logger.info(
            "telemetry_event_published",
            correlation_id=correlation_id,
            event_type="telemetry.metric.ingested",
            metric=payload["metric"],
            device_id=payload["device_id"],
            stream_entry_id=entry_id,
        )
        return entry_id

    async def _increment_ingested_counter(self, correlation_id: str) -> None:
        try:
            await self._counter_service.increment_ingested()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "telemetry_ingested_counter_increment_failed",
                correlation_id=correlation_id,
                error=str(exc),
            )


class TelemetryCollectorRunner(TelemetryCollector):
    """Minimal no-op collector runner for VS2 bootstrap wiring.

    This runner does not pull real SNMP/gRPC data yet. It only exposes
    lifecycle hooks and a callable ingestion path for tests and future wiring.
    """

    def __init__(
        self,
        ingestion_service: TelemetryIngestionService,
        counter_service: TelemetryHealthCounterService | None = None,
    ):
        self._ingestion_service = ingestion_service
        self._counter_service = counter_service or ingestion_service.counter_service
        self._event_redis = ingestion_service.redis
        self._running = False
        self._runtime_loop_task: asyncio.Task | None = None
        self._runtime_stop_event = asyncio.Event()
        self._runtime_exhausted_streak = 0
        self._runtime_sustained_failure_active = False

    @property
    def running(self) -> bool:
        return self._running

    @property
    def counter_service(self) -> TelemetryHealthCounterService:
        return self._counter_service

    async def start(self) -> None:
        self._running = True
        logger.info("telemetry_collector_started")

    async def stop(self) -> None:
        self._running = False
        await self.stop_runtime_loop()
        logger.info("telemetry_collector_stopped")

    async def start_runtime_loop(
        self,
        *,
        poll_action: Callable[[], Awaitable[None]],
        interval_seconds: float,
        poll_max_attempts: int,
        poll_base_backoff_seconds: float,
        poll_max_backoff_seconds: float,
        runtime_sustained_failure_threshold: int = _RUNTIME_SUSTAINED_FAILURE_DEFAULT_THRESHOLD,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        """Start a deterministic runtime loop that executes one poll cycle per interval."""
        if self._runtime_loop_task is not None and not self._runtime_loop_task.done():
            logger.info("telemetry_collector_runtime_loop_already_running")
            return

        self._runtime_stop_event = asyncio.Event()
        self._runtime_exhausted_streak = 0
        self._runtime_sustained_failure_active = False
        await self._safe_runtime_counter_update(
            lambda: self._counter_service.set_runtime_exhausted_streak(0),
            counter_name="runtime_exhausted_streak",
        )
        await self._safe_runtime_counter_update(
            lambda: self._counter_service.set_runtime_sustained_failure_active(False),
            counter_name="runtime_sustained_failure_active",
        )
        interval = max(interval_seconds, 0.0)
        threshold = max(1, runtime_sustained_failure_threshold)
        self._runtime_loop_task = asyncio.create_task(
            self._run_runtime_loop(
                poll_action=poll_action,
                interval_seconds=interval,
                poll_max_attempts=poll_max_attempts,
                poll_base_backoff_seconds=poll_base_backoff_seconds,
                poll_max_backoff_seconds=poll_max_backoff_seconds,
                runtime_sustained_failure_threshold=threshold,
                sleep=sleep,
            ),
            name="telemetry-runtime-loop",
        )
        logger.info(
            "telemetry_collector_runtime_loop_started",
            interval_seconds=interval,
            poll_max_attempts=max(1, poll_max_attempts),
            runtime_sustained_failure_threshold=threshold,
        )

    async def stop_runtime_loop(self) -> None:
        """Stop runtime loop deterministically and await task completion."""
        task = self._runtime_loop_task
        if task is None:
            return

        self._runtime_stop_event.set()
        await task
        self._runtime_loop_task = None
        logger.info("telemetry_collector_runtime_loop_stopped")

    async def _run_runtime_loop(
        self,
        *,
        poll_action: Callable[[], Awaitable[None]],
        interval_seconds: float,
        poll_max_attempts: int,
        poll_base_backoff_seconds: float,
        poll_max_backoff_seconds: float,
        runtime_sustained_failure_threshold: int,
        sleep: Callable[[float], Awaitable[None]],
    ) -> None:
        while not self._runtime_stop_event.is_set():
            succeeded = await self.run_single_poll_with_retry(
                poll_action=poll_action,
                max_attempts=poll_max_attempts,
                base_backoff_seconds=poll_base_backoff_seconds,
                max_backoff_seconds=poll_max_backoff_seconds,
                sleep=sleep,
            )

            if not succeeded:
                await self._record_runtime_cycle_exhausted(
                    sustained_failure_threshold=runtime_sustained_failure_threshold
                )
            else:
                await self._record_runtime_cycle_success(
                    sustained_failure_threshold=runtime_sustained_failure_threshold
                )

            if self._runtime_stop_event.is_set():
                break

            await sleep(interval_seconds)

    async def _record_runtime_cycle_exhausted(self, *, sustained_failure_threshold: int) -> None:
        self._runtime_exhausted_streak += 1
        await self._safe_runtime_counter_update(
            lambda: self._counter_service.increment_runtime_exhausted_cycle(),
            counter_name="runtime_exhausted_cycles",
        )
        await self._safe_runtime_counter_update(
            lambda: self._counter_service.set_runtime_exhausted_streak(self._runtime_exhausted_streak),
            counter_name="runtime_exhausted_streak",
        )

        logger.warning(
            "telemetry_collector_runtime_cycle_exhausted",
            exhausted_streak=self._runtime_exhausted_streak,
            sustained_failure_threshold=sustained_failure_threshold,
        )

        if (
            self._runtime_exhausted_streak >= sustained_failure_threshold
            and not self._runtime_sustained_failure_active
        ):
            self._runtime_sustained_failure_active = True
            await self._safe_runtime_counter_update(
                lambda: self._counter_service.increment_runtime_sustained_failure_window(),
                counter_name="runtime_sustained_failure_windows",
            )
            await self._safe_runtime_counter_update(
                lambda: self._counter_service.set_runtime_sustained_failure_active(True),
                counter_name="runtime_sustained_failure_active",
            )
            logger.warning(
                "telemetry_collector_runtime_sustained_failure_active",
                exhausted_streak=self._runtime_exhausted_streak,
                sustained_failure_threshold=sustained_failure_threshold,
            )
            await self._emit_runtime_transition_event(
                event_type=_RUNTIME_SUSTAINED_FAILURE_ACTIVATED_EVENT_TYPE,
                exhausted_streak=self._runtime_exhausted_streak,
                sustained_failure_threshold=sustained_failure_threshold,
            )

    async def _record_runtime_cycle_success(self, *, sustained_failure_threshold: int) -> None:
        if self._runtime_exhausted_streak == 0 and not self._runtime_sustained_failure_active:
            return

        previous_streak = self._runtime_exhausted_streak
        self._runtime_exhausted_streak = 0
        await self._safe_runtime_counter_update(
            lambda: self._counter_service.set_runtime_exhausted_streak(0),
            counter_name="runtime_exhausted_streak",
        )

        if self._runtime_sustained_failure_active:
            self._runtime_sustained_failure_active = False
            await self._safe_runtime_counter_update(
                lambda: self._counter_service.set_runtime_sustained_failure_active(False),
                counter_name="runtime_sustained_failure_active",
            )
            logger.info(
                "telemetry_collector_runtime_sustained_failure_recovered",
                previous_exhausted_streak=previous_streak,
            )
            await self._emit_runtime_transition_event(
                event_type=_RUNTIME_SUSTAINED_FAILURE_RECOVERED_EVENT_TYPE,
                exhausted_streak=previous_streak,
                sustained_failure_threshold=sustained_failure_threshold,
            )
        else:
            logger.info(
                "telemetry_collector_runtime_exhausted_streak_recovered",
                previous_exhausted_streak=previous_streak,
            )

    async def _emit_runtime_transition_event(
        self,
        *,
        event_type: str,
        exhausted_streak: int,
        sustained_failure_threshold: int,
    ) -> None:
        correlation_id = str(uuid.uuid4())
        payload = {
            "exhausted_streak": exhausted_streak,
            "sustained_failure_threshold": sustained_failure_threshold,
            "observed_at": datetime.now(UTC).isoformat(),
        }
        try:
            stream_entry_id = await publish_event(
                redis=self._event_redis,
                event_type=event_type,
                source="telemetry",
                payload=payload,
                correlation_id=correlation_id,
            )
            logger.info(
                "telemetry_collector_runtime_transition_event_published",
                event_type=event_type,
                stream_entry_id=stream_entry_id,
                correlation_id=correlation_id,
                exhausted_streak=exhausted_streak,
                sustained_failure_threshold=sustained_failure_threshold,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "telemetry_collector_runtime_transition_event_publish_failed",
                event_type=event_type,
                correlation_id=correlation_id,
                error=str(exc),
            )

    async def _safe_runtime_counter_update(
        self,
        updater: Callable[[], Awaitable[int]],
        *,
        counter_name: str,
    ) -> None:
        try:
            await updater()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "telemetry_collector_runtime_counter_update_failed",
                counter_name=counter_name,
                error=str(exc),
            )

    async def start_with_retry(
        self,
        *,
        max_attempts: int,
        base_backoff_seconds: float,
        max_backoff_seconds: float,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> bool:
        """Start collector with bounded retry/backoff and explicit failure visibility."""
        attempts = max(1, max_attempts)

        for attempt in range(1, attempts + 1):
            try:
                await self.start()
                logger.info(
                    "telemetry_collector_started_with_retry",
                    attempt=attempt,
                    max_attempts=attempts,
                )
                return True
            except Exception as exc:  # noqa: BLE001
                self._running = False
                if attempt >= attempts:
                    logger.warning(
                        "telemetry_collector_start_retries_exhausted",
                        attempt=attempt,
                        max_attempts=attempts,
                        error=str(exc),
                    )
                    return False

                delay = compute_bounded_backoff_seconds(
                    attempt,
                    base_backoff_seconds=base_backoff_seconds,
                    max_backoff_seconds=max_backoff_seconds,
                )
                logger.warning(
                    "telemetry_collector_start_retry_scheduled",
                    attempt=attempt,
                    max_attempts=attempts,
                    retry_in_seconds=delay,
                    error=str(exc),
                )
                await sleep(delay)

        return False

    async def run_single_poll_with_retry(
        self,
        *,
        poll_action: Callable[[], Awaitable[None]],
        max_attempts: int,
        base_backoff_seconds: float,
        max_backoff_seconds: float,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> bool:
        """Run one collector poll action with deterministic bounded retry/backoff."""
        attempts = max(1, max_attempts)

        for attempt in range(1, attempts + 1):
            try:
                await poll_action()
                if attempt > 1:
                    logger.info(
                        "telemetry_collector_poll_recovered",
                        attempt=attempt,
                        max_attempts=attempts,
                    )
                return True
            except Exception as exc:  # noqa: BLE001
                if attempt >= attempts:
                    logger.warning(
                        "telemetry_collector_poll_retries_exhausted",
                        attempt=attempt,
                        max_attempts=attempts,
                        error=str(exc),
                    )
                    return False

                delay = compute_bounded_backoff_seconds(
                    attempt,
                    base_backoff_seconds=base_backoff_seconds,
                    max_backoff_seconds=max_backoff_seconds,
                )
                logger.warning(
                    "telemetry_collector_poll_retry_scheduled",
                    attempt=attempt,
                    max_attempts=attempts,
                    retry_in_seconds=delay,
                    error=str(exc),
                )
                await sleep(delay)

        return False

    async def ingest_once(self, raw: dict[str, Any], correlation_id: str) -> str:
        return await self._ingestion_service.ingest(raw=raw, correlation_id=correlation_id)


class TelemetryPersistenceService:
    """Persist normalized telemetry events into telemetry_records."""

    def __init__(self, db: AsyncSession):
        self._repo = TelemetryRecordRepository(db)

    async def persist_event(self, event: dict[str, Any]) -> bool:
        event_id = self._parse_uuid(event.get("event_id"), field_name="event_id")
        existing = await self._repo.get_by_event_id(event_id)
        if existing is not None:
            return False

        correlation_id = self._parse_uuid(event.get("correlation_id"), field_name="correlation_id")
        payload = event.get("payload")
        if not isinstance(payload, dict):
            raise TypeError("payload must be an object")

        device_id = self._parse_uuid(payload.get("device_id"), field_name="payload.device_id")
        network_id = self._parse_uuid(payload.get("network_id"), field_name="payload.network_id")
        workspace_id = self._parse_uuid(payload.get("workspace_id"), field_name="payload.workspace_id")

        metric = self._parse_metric(payload.get("metric"))
        value = self._parse_value(payload.get("value"))
        unit = self._parse_optional_text(payload.get("unit"))
        observed_at = self._parse_datetime(payload.get("observed_at"), field_name="payload.observed_at")
        source = self._parse_source(payload.get("source"))

        tags_raw = payload.get("tags")
        tags = tags_raw if isinstance(tags_raw, dict) else {}

        await self._repo.create(
            event_id=event_id,
            correlation_id=correlation_id,
            device_id=device_id,
            network_id=network_id,
            workspace_id=workspace_id,
            metric=metric,
            value=value,
            unit=unit,
            observed_at=observed_at,
            source=source,
            tags=tags,
        )
        return True

    @staticmethod
    def _parse_uuid(value: Any, *, field_name: str) -> uuid.UUID:
        try:
            return uuid.UUID(str(value))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError(f"invalid uuid for {field_name}") from exc

    @staticmethod
    def _parse_metric(value: Any) -> str:
        metric = str(value or "").strip()
        if not metric:
            raise ValueError("payload.metric is required")
        return metric

    @staticmethod
    def _parse_source(value: Any) -> str:
        source = str(value or "collector").strip()
        if not source:
            raise ValueError("payload.source is required")
        return source

    @staticmethod
    def _parse_value(value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("payload.value must be numeric") from exc

    @staticmethod
    def _parse_optional_text(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _parse_datetime(value: Any, *, field_name: str) -> datetime:
        if value is None:
            raise ValueError(f"{field_name} is required")

        try:
            dt = datetime.fromisoformat(str(value))
        except ValueError as exc:
            raise ValueError(f"invalid datetime for {field_name}") from exc

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt


class TelemetryQueryService:
    """Read-side service for telemetry history, device metrics, and health."""

    def __init__(
        self,
        db: AsyncSession,
        counter_service: TelemetryHealthCounterService | None = None,
    ):
        self._repo = TelemetryRecordRepository(db)
        self._counter_service = counter_service

    async def get_history(
        self,
        *,
        network_id: uuid.UUID | None,
        workspace_id: uuid.UUID | None,
        metric: str | None,
        page: int,
        page_size: int,
    ) -> TelemetryHistoryResponse:
        rows, total = await self._repo.list_history(
            network_id=network_id,
            workspace_id=workspace_id,
            metric=metric,
            page=page,
            page_size=page_size,
        )
        return TelemetryHistoryResponse(
            items=[TelemetryRecordResponse.model_validate(row) for row in rows],
            total=total,
            page=page,
            page_size=page_size,
        )

    async def get_device_history(
        self,
        *,
        device_id: uuid.UUID,
        metric: str | None,
        page: int,
        page_size: int,
    ) -> TelemetryDeviceHistoryResponse:
        rows, total = await self._repo.list_for_device(
            device_id=device_id,
            metric=metric,
            page=page,
            page_size=page_size,
        )
        return TelemetryDeviceHistoryResponse(
            device_id=device_id,
            items=[TelemetryRecordResponse.model_validate(row) for row in rows],
            total=total,
            page=page,
            page_size=page_size,
        )

    async def get_health(self) -> TelemetryHealthResponse:
        latest_observed_at = await self._repo.get_latest_observed_at()
        total_records = await self._repo.count_all()
        counters = await self._get_counter_snapshot()
        dropped_events = counters["dropped_events"]
        runtime_sustained_failure_active = counters.get("runtime_sustained_failure_active", 0) > 0
        status = "degraded" if runtime_sustained_failure_active else "ok"

        if latest_observed_at is None:
            return TelemetryHealthResponse(
                status=status,
                ingest_lag_ms=0,
                dropped_events=dropped_events,
                latest_observed_at=None,
                total_records=0,
            )

        now_utc = datetime.now(UTC)
        lag_ms = int(max((now_utc - latest_observed_at).total_seconds() * 1000, 0))
        return TelemetryHealthResponse(
            status=status,
            ingest_lag_ms=lag_ms,
            dropped_events=dropped_events,
            latest_observed_at=latest_observed_at,
            total_records=total_records,
        )

    async def _get_counter_snapshot(self) -> dict[str, int]:
        if self._counter_service is None:
            return {
                "ingested_events": 0,
                "persisted_events": 0,
                "fanout_events": 0,
                "dropped_events": 0,
                "runtime_exhausted_cycles": 0,
                "runtime_exhausted_streak": 0,
                "runtime_sustained_failure_windows": 0,
                "runtime_sustained_failure_active": 0,
                "runtime_adapter_last_batch_size": 0,
                "runtime_adapter_invalid_samples": 0,
                "runtime_adapter_ingest_attempts": 0,
                "runtime_adapter_ingest_failures": 0,
            }
        try:
            return await self._counter_service.get_snapshot()
        except Exception as exc:  # noqa: BLE001
            logger.warning("telemetry_health_counter_snapshot_failed", error=str(exc))
            return {
                "ingested_events": 0,
                "persisted_events": 0,
                "fanout_events": 0,
                "dropped_events": 0,
                "runtime_exhausted_cycles": 0,
                "runtime_exhausted_streak": 0,
                "runtime_sustained_failure_windows": 0,
                "runtime_sustained_failure_active": 0,
                "runtime_adapter_last_batch_size": 0,
                "runtime_adapter_invalid_samples": 0,
                "runtime_adapter_ingest_attempts": 0,
                "runtime_adapter_ingest_failures": 0,
            }

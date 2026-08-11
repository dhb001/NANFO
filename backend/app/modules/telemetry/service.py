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
from collections import deque
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
_RUNTIME_ADAPTER_INVALID_SAMPLE_RATIO_WARN_THRESHOLD = 0.25
_RUNTIME_ADAPTER_ANOMALY_STREAK_CRITICAL_THRESHOLD = 3
_RUNTIME_ADAPTER_SLO_TREND_WINDOW_MAX_SIZE = 10


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
        self._runtime_adapter_slo_trend_window: deque[dict[str, Any]] = deque(
            maxlen=_RUNTIME_ADAPTER_SLO_TREND_WINDOW_MAX_SIZE
        )

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
        runtime_adapter_anomaly_streak = self._coerce_non_negative_counter(
            counters.get("runtime_adapter_anomaly_streak", 0),
            counter_name="runtime_adapter_anomaly_streak",
        )
        runtime_adapter_slo_snapshot = self._build_runtime_adapter_slo_snapshot(counters)
        await self._safe_log_runtime_adapter_slo_snapshot(
            runtime_adapter_slo_snapshot=runtime_adapter_slo_snapshot,
            runtime_adapter_anomaly_streak=runtime_adapter_anomaly_streak,
            runtime_sustained_failure_active=runtime_sustained_failure_active,
            status=status,
            dropped_events=dropped_events,
        )

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

    def _build_runtime_adapter_slo_snapshot(self, counters: dict[str, Any]) -> dict[str, int]:
        return {
            "last_batch_size": self._coerce_non_negative_counter(
                counters.get("runtime_adapter_last_batch_size", 0),
                counter_name="runtime_adapter_last_batch_size",
            ),
            "invalid_samples": self._coerce_non_negative_counter(
                counters.get("runtime_adapter_invalid_samples", 0),
                counter_name="runtime_adapter_invalid_samples",
            ),
            "ingest_attempts": self._coerce_non_negative_counter(
                counters.get("runtime_adapter_ingest_attempts", 0),
                counter_name="runtime_adapter_ingest_attempts",
            ),
            "ingest_failures": self._coerce_non_negative_counter(
                counters.get("runtime_adapter_ingest_failures", 0),
                counter_name="runtime_adapter_ingest_failures",
            ),
        }

    @staticmethod
    def _coerce_non_negative_counter(value: Any, *, counter_name: str) -> int:
        try:
            numeric = int(value)
        except (TypeError, ValueError):
            logger.warning(
                "telemetry_health_runtime_adapter_counter_invalid",
                counter_name=counter_name,
                raw_value=str(value),
            )
            return 0

        if numeric < 0:
            logger.warning(
                "telemetry_health_runtime_adapter_counter_invalid",
                counter_name=counter_name,
                raw_value=str(value),
            )
            return 0

        return numeric

    async def _safe_log_runtime_adapter_slo_snapshot(
        self,
        *,
        runtime_adapter_slo_snapshot: dict[str, int],
        runtime_adapter_anomaly_streak: int,
        runtime_sustained_failure_active: bool,
        status: str,
        dropped_events: int,
    ) -> None:
        try:
            logger.info(
                "telemetry_health_runtime_adapter_slo_snapshot",
                status=status,
                dropped_events=dropped_events,
                last_batch_size=runtime_adapter_slo_snapshot["last_batch_size"],
                invalid_samples=runtime_adapter_slo_snapshot["invalid_samples"],
                ingest_attempts=runtime_adapter_slo_snapshot["ingest_attempts"],
                ingest_failures=runtime_adapter_slo_snapshot["ingest_failures"],
            )
            anomaly_reason_flags = self._log_runtime_adapter_backpressure_anomalies(
                runtime_adapter_slo_snapshot=runtime_adapter_slo_snapshot
            )
            current_anomaly_streak = await self._update_runtime_adapter_anomaly_streak(
                anomaly_reason_flags=anomaly_reason_flags,
                runtime_adapter_anomaly_streak=runtime_adapter_anomaly_streak,
            )
            rollup_severity, _ = self._log_runtime_adapter_slo_health_rollup(
                runtime_adapter_slo_snapshot=runtime_adapter_slo_snapshot,
                runtime_adapter_anomaly_streak=current_anomaly_streak,
                runtime_sustained_failure_active=runtime_sustained_failure_active,
                anomaly_reason_flags=anomaly_reason_flags,
            )
            self._safe_log_runtime_adapter_slo_trend_window_summary(
                severity=rollup_severity,
                anomaly_reason_flags=anomaly_reason_flags,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "telemetry_health_runtime_adapter_slo_snapshot_log_failed",
                status=status,
                dropped_events=dropped_events,
                error=str(exc),
            )

    def _safe_log_runtime_adapter_slo_trend_window_summary(
        self,
        *,
        severity: str,
        anomaly_reason_flags: list[str],
    ) -> None:
        try:
            self._append_runtime_adapter_slo_trend_window_entry(
                severity=severity,
                anomaly_reason_flags=anomaly_reason_flags,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "telemetry_health_runtime_adapter_slo_trend_window_state_write_failed",
                error=str(exc),
            )
            return

        try:
            trend_window_summary = self._build_runtime_adapter_slo_trend_window_summary()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "telemetry_health_runtime_adapter_slo_trend_window_state_read_failed",
                error=str(exc),
            )
            return

        try:
            logger.info(
                "telemetry_health_runtime_adapter_slo_trend_window_summary",
                latest_severity=severity,
                latest_anomaly_reason_flags=anomaly_reason_flags,
                window_size=trend_window_summary["window_size"],
                max_window_size=trend_window_summary["max_window_size"],
                severity_transition_counts=trend_window_summary["severity_transition_counts"],
                anomaly_reason_frequency=trend_window_summary["anomaly_reason_frequency"],
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "telemetry_health_runtime_adapter_slo_trend_window_log_failed",
                error=str(exc),
            )

    def _append_runtime_adapter_slo_trend_window_entry(
        self,
        *,
        severity: str,
        anomaly_reason_flags: list[str],
    ) -> None:
        self._runtime_adapter_slo_trend_window.append(
            {
                "severity": severity,
                "anomaly_reason_flags": tuple(anomaly_reason_flags),
            }
        )

    def _build_runtime_adapter_slo_trend_window_summary(self) -> dict[str, Any]:
        entries = list(self._runtime_adapter_slo_trend_window)
        severity_transition_counts: dict[str, int] = {}
        anomaly_reason_frequency: dict[str, int] = {}

        for index in range(1, len(entries)):
            previous_severity = str(entries[index - 1]["severity"])
            current_severity = str(entries[index]["severity"])
            transition_key = f"{previous_severity}->{current_severity}"
            severity_transition_counts[transition_key] = (
                severity_transition_counts.get(transition_key, 0) + 1
            )

        for entry in entries:
            for reason in entry["anomaly_reason_flags"]:
                anomaly_reason_frequency[str(reason)] = (
                    anomaly_reason_frequency.get(str(reason), 0) + 1
                )

        return {
            "window_size": len(entries),
            "max_window_size": int(self._runtime_adapter_slo_trend_window.maxlen or 0),
            "severity_transition_counts": dict(sorted(severity_transition_counts.items())),
            "anomaly_reason_frequency": dict(sorted(anomaly_reason_frequency.items())),
        }

    def _log_runtime_adapter_slo_health_rollup(
        self,
        *,
        runtime_adapter_slo_snapshot: dict[str, int],
        runtime_adapter_anomaly_streak: int,
        runtime_sustained_failure_active: bool,
        anomaly_reason_flags: list[str],
    ) -> tuple[str, str]:
        ingest_attempts = runtime_adapter_slo_snapshot["ingest_attempts"]
        ingest_failures = runtime_adapter_slo_snapshot["ingest_failures"]
        invalid_samples = runtime_adapter_slo_snapshot["invalid_samples"]
        invalid_sample_ratio = self._compute_invalid_sample_ratio(
            invalid_samples=invalid_samples,
            ingest_attempts=ingest_attempts,
        )
        severity, severity_reason = self._resolve_runtime_adapter_slo_rollup_severity(
            runtime_adapter_anomaly_streak=runtime_adapter_anomaly_streak,
            runtime_sustained_failure_active=runtime_sustained_failure_active,
            anomaly_reason_flags=anomaly_reason_flags,
        )
        if severity == "ok":
            log_fn = logger.info
        elif severity == "degraded":
            log_fn = logger.warning
        else:
            log_fn = logger.error

        log_fn(
            "telemetry_health_runtime_adapter_slo_rollup",
            severity=severity,
            severity_reason=severity_reason,
            runtime_adapter_anomaly_streak=runtime_adapter_anomaly_streak,
            runtime_sustained_failure_active=runtime_sustained_failure_active,
            ingest_attempts=ingest_attempts,
            ingest_failures=ingest_failures,
            invalid_samples=invalid_samples,
            invalid_sample_ratio=invalid_sample_ratio,
            last_batch_size=runtime_adapter_slo_snapshot["last_batch_size"],
            anomaly_reason_flags=anomaly_reason_flags,
            anomaly_streak_critical_threshold=_RUNTIME_ADAPTER_ANOMALY_STREAK_CRITICAL_THRESHOLD,
        )
        return severity, severity_reason

    @staticmethod
    def _resolve_runtime_adapter_slo_rollup_severity(
        *,
        runtime_adapter_anomaly_streak: int,
        runtime_sustained_failure_active: bool,
        anomaly_reason_flags: list[str],
    ) -> tuple[str, str]:
        if runtime_sustained_failure_active:
            return "critical", "runtime_sustained_failure_active"

        if runtime_adapter_anomaly_streak >= _RUNTIME_ADAPTER_ANOMALY_STREAK_CRITICAL_THRESHOLD:
            return "critical", "anomaly_streak_threshold_exceeded"

        if anomaly_reason_flags or runtime_adapter_anomaly_streak > 0:
            return "degraded", "runtime_adapter_anomaly_detected"

        return "ok", "runtime_adapter_healthy"

    @staticmethod
    def _compute_invalid_sample_ratio(*, invalid_samples: int, ingest_attempts: int) -> float:
        total_samples = invalid_samples + ingest_attempts
        return (invalid_samples / total_samples) if total_samples > 0 else 0.0

    def _log_runtime_adapter_backpressure_anomalies(
        self,
        *,
        runtime_adapter_slo_snapshot: dict[str, int],
    ) -> list[str]:
        ingest_attempts = runtime_adapter_slo_snapshot["ingest_attempts"]
        ingest_failures = runtime_adapter_slo_snapshot["ingest_failures"]
        invalid_samples = runtime_adapter_slo_snapshot["invalid_samples"]
        anomaly_reason_flags: list[str] = []

        if ingest_failures > 0:
            anomaly_reason_flags.append("ingest_failures_detected")
            zero_attempt_guard_applied = ingest_attempts == 0
            denominator = ingest_attempts if ingest_attempts > 0 else 1
            failure_ratio = ingest_failures / denominator
            logger.warning(
                "telemetry_health_runtime_adapter_ingest_failures_detected",
                ingest_failures=ingest_failures,
                ingest_attempts=ingest_attempts,
                failure_ratio=failure_ratio,
                zero_attempt_guard_applied=zero_attempt_guard_applied,
            )

        invalid_sample_ratio = self._compute_invalid_sample_ratio(
            invalid_samples=invalid_samples,
            ingest_attempts=ingest_attempts,
        )
        if invalid_sample_ratio > _RUNTIME_ADAPTER_INVALID_SAMPLE_RATIO_WARN_THRESHOLD:
            anomaly_reason_flags.append("invalid_sample_ratio_exceeded")
            logger.warning(
                "telemetry_health_runtime_adapter_invalid_sample_ratio_exceeded",
                invalid_samples=invalid_samples,
                ingest_attempts=ingest_attempts,
                invalid_sample_ratio=invalid_sample_ratio,
                invalid_sample_ratio_threshold=_RUNTIME_ADAPTER_INVALID_SAMPLE_RATIO_WARN_THRESHOLD,
            )

        return anomaly_reason_flags

    async def _update_runtime_adapter_anomaly_streak(
        self,
        *,
        anomaly_reason_flags: list[str],
        runtime_adapter_anomaly_streak: int,
    ) -> int:
        previous_streak = runtime_adapter_anomaly_streak

        if anomaly_reason_flags:
            updated_streak = runtime_adapter_anomaly_streak + 1
            logger.warning(
                "telemetry_health_runtime_adapter_anomaly_streak_incremented",
                anomaly_streak=updated_streak,
            )
            await self._persist_runtime_adapter_anomaly_streak(streak=updated_streak)
            self._log_runtime_adapter_anomaly_streak_transition(
                previous_streak=previous_streak,
                current_streak=updated_streak,
                anomaly_reason_flags=anomaly_reason_flags,
            )
            return updated_streak

        if runtime_adapter_anomaly_streak > 0:
            logger.info(
                "telemetry_health_runtime_adapter_anomaly_streak_reset",
                previous_streak=runtime_adapter_anomaly_streak,
            )
            await self._persist_runtime_adapter_anomaly_streak(streak=0)
            self._log_runtime_adapter_anomaly_streak_transition(
                previous_streak=previous_streak,
                current_streak=0,
                anomaly_reason_flags=anomaly_reason_flags,
            )
            return 0

        self._log_runtime_adapter_anomaly_streak_transition(
            previous_streak=previous_streak,
            current_streak=previous_streak,
            anomaly_reason_flags=anomaly_reason_flags,
        )
        return previous_streak

    def _log_runtime_adapter_anomaly_streak_transition(
        self,
        *,
        previous_streak: int,
        current_streak: int,
        anomaly_reason_flags: list[str],
    ) -> None:
        log_fn = logger.warning if current_streak > previous_streak else logger.info
        log_fn(
            "telemetry_health_runtime_adapter_anomaly_streak_transition",
            previous_streak=previous_streak,
            current_streak=current_streak,
            anomaly_reason_flags=anomaly_reason_flags,
        )

    async def _persist_runtime_adapter_anomaly_streak(self, *, streak: int) -> None:
        if self._counter_service is None:
            return
        try:
            await self._counter_service.set_runtime_adapter_anomaly_streak(streak)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "telemetry_health_runtime_adapter_anomaly_streak_persist_failed",
                anomaly_streak=streak,
                error=str(exc),
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
                "runtime_adapter_anomaly_streak": 0,
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
                "runtime_adapter_anomaly_streak": 0,
            }

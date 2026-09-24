"""Collector lifecycle, bounded retry/backoff and the periodic runtime loop.

The runtime loop is also the placement of the periodic SLO evaluator (C12): after
every poll cycle it gives ``TelemetrySLOEvaluator`` a chance to close its window.
The evaluator is window-gated and lock-guarded in Redis, so extra calls are cheap
and replicas never double-evaluate. Health reads never evaluate or publish.
"""

from __future__ import annotations

import asyncio
import uuid
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from app.core.logging import get_logger
from app.events.publisher import publish_event
from app.modules.telemetry.counters import TelemetryHealthCounterService

if TYPE_CHECKING:
    from app.modules.telemetry.ingestion import TelemetryIngestionService
    from app.modules.telemetry.slo.evaluator import TelemetrySLOEvaluator

logger = get_logger(__name__)

_RUNTIME_SUSTAINED_FAILURE_DEFAULT_THRESHOLD = 3
_RUNTIME_SUSTAINED_FAILURE_ACTIVATED_EVENT_TYPE = "telemetry.collector.sustained_failure_activated"
_RUNTIME_SUSTAINED_FAILURE_RECOVERED_EVENT_TYPE = "telemetry.collector.sustained_failure_recovered"
_DEFAULT_SLO = object()


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
    return min(base * (2 ** (attempt - 1)), cap)


class TelemetryCollector(ABC):
    """Lifecycle interface for telemetry collectors."""

    @abstractmethod
    async def start(self) -> None:
        pass

    @abstractmethod
    async def stop(self) -> None:
        pass


class TelemetryCollectorRunner(TelemetryCollector):
    """Collector runner: lifecycle hooks, retrying runtime loop and ingestion path."""

    def __init__(
        self,
        ingestion_service: TelemetryIngestionService,
        counter_service: TelemetryHealthCounterService | None = None,
        *,
        slo_evaluator: TelemetrySLOEvaluator | None | Any = _DEFAULT_SLO,
    ):
        self._ingestion_service = ingestion_service
        self._counter_service = counter_service or ingestion_service.counter_service
        self._event_redis = ingestion_service.redis
        self._running = False
        self._runtime_loop_task: asyncio.Task | None = None
        self._runtime_stop_event = asyncio.Event()
        self._runtime_exhausted_streak = 0
        self._runtime_sustained_failure_active = False
        if slo_evaluator is _DEFAULT_SLO:
            from app.modules.telemetry.slo.evaluator import TelemetrySLOEvaluator

            try:
                slo_evaluator = TelemetrySLOEvaluator(redis=self._event_redis, counter_service=self._counter_service)
            except ValueError as exc:  # invalid NANFO_TELEMETRY_SLO_* never blocks collection
                logger.warning("telemetry_slo_evaluator_disabled", error_code="slo_settings_invalid",
                               error_type=type(exc).__name__)
                slo_evaluator = None
        self._slo_evaluator = slo_evaluator

    @property
    def running(self) -> bool:
        return self._running

    @property
    def runtime_healthy(self) -> bool:
        return (
            self._running
            and self._runtime_loop_task is not None
            and not self._runtime_loop_task.done()
            and self._runtime_exhausted_streak == 0
        )

    @property
    def counter_service(self) -> TelemetryHealthCounterService:
        return self._counter_service

    @property
    def slo_evaluator(self) -> TelemetrySLOEvaluator | None:
        return self._slo_evaluator

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
            await self._evaluate_slo()
            if self._runtime_stop_event.is_set():
                break
            await sleep(interval_seconds)

    async def _evaluate_slo(self) -> None:
        if self._slo_evaluator is None:
            return
        settings = getattr(self._slo_evaluator, "settings", None)
        budget = float(getattr(settings, "lock_seconds", 10.0) or 10.0)
        try:
            async with asyncio.timeout(budget):
                await self._slo_evaluator.maybe_evaluate()
        except Exception as exc:  # noqa: BLE001 - evaluation never stops collection
            logger.warning("telemetry_slo_evaluation_failed", error_code="slo_evaluation_failed",
                           error_type=type(exc).__name__)

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
        self, *, event_type: str, exhausted_streak: int, sustained_failure_threshold: int,
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
                error_type=type(exc).__name__,
            )

    async def _safe_runtime_counter_update(
        self, updater: Callable[[], Awaitable[int]], *, counter_name: str,
    ) -> None:
        try:
            await updater()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "telemetry_collector_runtime_counter_update_failed",
                counter_name=counter_name,
                error_type=type(exc).__name__,
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
                logger.info("telemetry_collector_started_with_retry", attempt=attempt, max_attempts=attempts)
                return True
            except Exception as exc:  # noqa: BLE001
                self._running = False
                if attempt >= attempts:
                    logger.warning(
                        "telemetry_collector_start_retries_exhausted",
                        attempt=attempt, max_attempts=attempts, error_type=type(exc).__name__, error=str(exc),
                    )
                    return False
                delay = compute_bounded_backoff_seconds(
                    attempt, base_backoff_seconds=base_backoff_seconds, max_backoff_seconds=max_backoff_seconds,
                )
                logger.warning(
                    "telemetry_collector_start_retry_scheduled",
                    attempt=attempt, max_attempts=attempts, retry_in_seconds=delay,
                    error_type=type(exc).__name__, error=str(exc),
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
                    logger.info("telemetry_collector_poll_recovered", attempt=attempt, max_attempts=attempts)
                return True
            except Exception as exc:  # noqa: BLE001
                if attempt >= attempts:
                    logger.warning(
                        "telemetry_collector_poll_retries_exhausted",
                        attempt=attempt, max_attempts=attempts, error_type=type(exc).__name__, error=str(exc),
                    )
                    return False
                delay = compute_bounded_backoff_seconds(
                    attempt, base_backoff_seconds=base_backoff_seconds, max_backoff_seconds=max_backoff_seconds,
                )
                logger.warning(
                    "telemetry_collector_poll_retry_scheduled",
                    attempt=attempt, max_attempts=attempts, retry_in_seconds=delay,
                    error_type=type(exc).__name__, error=str(exc),
                )
                await sleep(delay)
        return False

    async def ingest_once(self, raw: dict[str, Any], correlation_id: str, *, event_id: str | None = None) -> str:
        event_options = {"event_id": event_id} if event_id is not None else {}
        return await self._ingestion_service.ingest(raw=raw, correlation_id=correlation_id, **event_options)

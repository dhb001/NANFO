"""Generic runtime poll action: adapter batch -> validation -> guarded ingestion."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from app.core.logging import get_logger
from app.modules.telemetry.runtime.adapters import RuntimeTelemetryAdapter
from app.modules.telemetry.validation import parse_observed_at

if TYPE_CHECKING:
    from app.modules.telemetry.runtime.runner import TelemetryCollectorRunner

logger = get_logger(__name__)


def _invalid_sample_reason(raw: dict[str, Any]) -> str | None:
    """Return a fixed rejection reason, or ``None`` for a minimally valid sample."""
    required_ids = ("device_id", "network_id", "workspace_id")
    if any(not str(raw.get(field, "")).strip() for field in required_ids):
        return "missing_required_fields"
    if not str(raw.get("metric", "")).strip():
        return "missing_required_fields"
    if raw.get("value") is None:
        return "missing_required_fields"
    observed_at = raw.get("observed_at")
    if observed_at is not None and observed_at != "":
        try:
            parse_observed_at(observed_at, field_name="observed_at")
        except ValueError:
            return "observed_at_invalid"
    return None


def _is_runtime_sample_minimally_valid(raw: dict[str, Any]) -> bool:
    return _invalid_sample_reason(raw) is None


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
            error_type=type(exc).__name__,
        )


def build_runtime_poll_action(
    *,
    collector_runner: TelemetryCollectorRunner,
    adapter: RuntimeTelemetryAdapter,
) -> Callable[[], Awaitable[None]]:
    """Build the runtime poll action that uses a production-shaped adapter."""

    async def _count_rejected(adapter_name: str) -> None:
        counters = collector_runner.counter_service
        await _safe_runtime_adapter_counter_update(
            counters.increment_runtime_adapter_invalid_sample,
            adapter_name=adapter_name, counter_name="runtime_adapter_invalid_samples",
        )
        await _safe_runtime_adapter_counter_update(
            counters.increment_runtime_adapter_dropped_sample,
            adapter_name=adapter_name, counter_name="runtime_adapter_dropped_samples",
        )

    async def _poll_action() -> None:
        adapter_name = adapter.__class__.__name__
        counters = collector_runner.counter_service
        try:
            samples = await adapter.poll()
        except Exception as exc:
            logger.warning(
                "telemetry_runtime_adapter_poll_failed",
                adapter=adapter_name,
                error_type=type(exc).__name__,
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
            lambda: counters.set_runtime_adapter_last_batch_size(batch_size),
            adapter_name=adapter_name,
            counter_name="runtime_adapter_last_batch_size",
        )

        batch_valid = True
        for sample in samples:
            reason = "sample_not_object" if not isinstance(sample, dict) else _invalid_sample_reason(sample)
            if reason is not None:
                batch_valid = False
                await _count_rejected(adapter_name)
                logger.warning(
                    "telemetry_runtime_adapter_sample_invalid",
                    adapter=adapter_name,
                    reason=reason,
                    sample_type=type(sample).__name__,
                )
                continue

            correlation_id = str(uuid.uuid4())
            await _safe_runtime_adapter_counter_update(
                counters.increment_runtime_adapter_ingest_attempt,
                adapter_name=adapter_name,
                counter_name="runtime_adapter_ingest_attempts",
            )
            try:
                event_options = {"event_id": sample["event_id"]} if sample.get("event_id") else {}
                await collector_runner.ingest_once(raw=sample, correlation_id=correlation_id, **event_options)
            except Exception as exc:
                await _safe_runtime_adapter_counter_update(
                    counters.increment_runtime_adapter_ingest_failure,
                    adapter_name=adapter_name,
                    counter_name="runtime_adapter_ingest_failures",
                )
                await _safe_runtime_adapter_counter_update(
                    counters.increment_runtime_adapter_dropped_sample,
                    adapter_name=adapter_name,
                    counter_name="runtime_adapter_dropped_samples",
                )
                logger.warning(
                    "telemetry_runtime_adapter_ingest_failed",
                    adapter=adapter_name,
                    correlation_id=correlation_id,
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
                raise

        if batch_valid:
            await adapter.acknowledge_batch(samples)

    return _poll_action

"""Persisted SLO evaluation state (Redis) and evaluator settings.

The state document is the single source of truth for SLO windows: baselines for
counter deltas, trend window, per-dimension cooldowns, alert episode and a small
pending-event outbox. Evaluation runs under a short Redis lock; health reads only
``load`` it.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

import redis.asyncio as aioredis
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.logging import get_logger

logger = get_logger(__name__)

STATE_KEY = "telemetry:slo:v1:state"
LOCK_KEY = "telemetry:slo:v1:lock"


class TelemetrySLOSettings(BaseSettings):
    """``NANFO_TELEMETRY_SLO_*`` environment; the evaluator runs in collector workers."""

    model_config = SettingsConfigDict(env_prefix="NANFO_TELEMETRY_SLO_", extra="ignore", hide_input_in_errors=True)

    enabled: bool = True
    interval_seconds: float = Field(default=30.0, ge=5, le=3600, allow_inf_nan=False)
    stale_after_intervals: int = Field(default=3, ge=2, le=100)
    lock_seconds: float = Field(default=10.0, ge=1, le=300, allow_inf_nan=False)


class SLOWindow(BaseModel):
    model_config = ConfigDict(extra="ignore")

    start: AwareDatetime | None = None
    end: AwareDatetime
    seconds: float = 0.0
    ingest_attempts: int = 0
    ingest_failures: int = 0
    invalid_samples: int = 0
    dropped_samples: int = 0
    last_batch_size: int = 0
    invalid_sample_ratio: float = 0.0
    counter_reset: bool = False

    def as_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class PendingEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    event_id: uuid.UUID
    event_type: Literal["alert.generated", "alert.resolved"]
    correlation_id: uuid.UUID
    payload: dict[str, Any]


class SLOState(BaseModel):
    model_config = ConfigDict(extra="ignore")

    version: Literal[1] = 1
    # A fresh epoch after a Redis reset keeps deterministic alert event ids unique.
    epoch: uuid.UUID = Field(default_factory=uuid.uuid4)
    sequence: int = 0
    evaluated_at: AwareDatetime | None = None
    baseline: dict[str, int] | None = None
    window: SLOWindow | None = None
    severity: Literal["ok", "degraded", "critical"] = "ok"
    severity_reason: str = "runtime_adapter_healthy"
    anomaly_reason_flags: list[str] = Field(default_factory=list)
    anomaly_streak: int = 0
    sustained_failure_active: bool = False
    alert_active: bool = False
    alert_episode: int = 0
    trend: list[dict[str, Any]] = Field(default_factory=list)
    cooldown: dict[str, dict[str, Any]] = Field(default_factory=dict)
    threshold_phase: dict[str, str] = Field(default_factory=dict)
    pending_events: list[PendingEvent] = Field(default_factory=list)


class SLOStateStore:
    def __init__(self, redis: aioredis.Redis):
        self._redis = redis

    async def load(self) -> SLOState | None:
        raw = await self._redis.get(STATE_KEY)
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        try:
            return SLOState.model_validate_json(raw)
        except ValueError:
            # A corrupt document restarts windows under a new epoch instead of
            # blocking evaluation forever; never guess at partial state.
            logger.warning("telemetry_slo_state_invalid", error_code="slo_state_invalid")
            return None

    async def save(self, state: SLOState) -> None:
        await self._redis.set(STATE_KEY, state.model_dump_json())

    async def acquire(self, token: str, *, ttl_seconds: float) -> bool:
        return bool(await self._redis.set(LOCK_KEY, token, nx=True, px=max(1, int(ttl_seconds * 1000))))

    async def release(self, token: str) -> None:
        current = await self._redis.get(LOCK_KEY)
        if isinstance(current, bytes):
            current = current.decode("utf-8")
        if current == token:
            await self._redis.delete(LOCK_KEY)


def is_due(state: SLOState | None, *, now: datetime, interval_seconds: float) -> bool:
    if state is None or state.evaluated_at is None:
        return True
    return (now - state.evaluated_at).total_seconds() >= interval_seconds

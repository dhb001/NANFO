"""ADR023 bounded, versioned internal broadcast contract (not a public API)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator


@dataclass(frozen=True)
class FanoutSettings:
    stream_key: str = "nanfo:{realtime}:v1:fanout"
    sequence_key: str = "nanfo:{realtime}:v1:sequence"
    lease_key: str = "nanfo:api:realtime:lease"
    max_entries: int = 4096
    max_payload_bytes: int = 262144
    batch_size: int = 32
    dedup_entries: int = 4096
    heartbeat_seconds: float = 1.0
    stale_seconds: float = 5.0
    io_timeout_seconds: float = 2.0
    lease_ttl_seconds: float = 30.0
    retry_seconds: float = 1.0
    shutdown_seconds: float = 5.0

    def __post_init__(self):
        for value in (self.max_entries, self.max_payload_bytes, self.batch_size, self.dedup_entries):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError("Fanout bounds must be positive integers")
        for value in (self.heartbeat_seconds, self.stale_seconds, self.io_timeout_seconds,
                      self.lease_ttl_seconds, self.retry_seconds, self.shutdown_seconds):
            if not math.isfinite(value) or value <= 0:
                raise ValueError("Fanout deadlines must be finite and positive")
        if self.stale_seconds <= self.heartbeat_seconds + self.io_timeout_seconds:
            raise ValueError("Freshness must exceed heartbeat plus IO deadline")
        if self.io_timeout_seconds <= self.heartbeat_seconds / 2:
            raise ValueError("IO timeout must exceed the blocking read interval")
        if self.lease_ttl_seconds < 0.006:
            raise ValueError("Lease TTL must support millisecond expiry and IO deadlines")
        if len({self.stream_key, self.sequence_key, self.lease_key}) != 3:
            raise ValueError("Fanout keys must be distinct")


class DeltaArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    network_id: str | None = Field(default=None, max_length=128)
    workspace_id: str | None = Field(default=None, max_length=128)
    event_type: str = Field(min_length=1, max_length=128)
    correlation_id: str = Field(max_length=128)
    timestamp: str = Field(min_length=1, max_length=128)
    delta_type: str | None = Field(default=None, max_length=32)
    node: dict[str, JsonValue] | None = None
    metric: dict[str, JsonValue] | None = None
    scene_object: dict[str, JsonValue] | None = None
    alert: dict[str, JsonValue] | None = None


class FanoutEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: Literal[1] = 1
    kind: Literal["delta", "heartbeat", "reset"]
    epoch: str = Field(min_length=1, max_length=128)
    sequence: int = Field(gt=0)
    published_at: float = Field(gt=0, allow_inf_nan=False)
    delivery_id: str = Field(min_length=1, max_length=256)
    channel: Literal["topology", "telemetry", "digital-twin", "alerts"] | None = None
    kwargs: DeltaArguments | None = None

    @model_validator(mode="after")
    def check_shape(self):
        if self.kind in ("heartbeat", "reset"):
            if self.channel is not None or self.kwargs is not None:
                raise ValueError("Control frame cannot carry a delta")
            return self
        if self.channel is None or self.kwargs is None:
            raise ValueError("Delta requires channel and arguments")
        args = self.kwargs
        body = {"topology": "node", "telemetry": "metric", "digital-twin": "scene_object", "alerts": "alert"}[self.channel]
        for name in ("node", "metric", "scene_object", "alert"):
            if (getattr(args, name) is not None) != (name == body):
                raise ValueError("Delta body does not match channel")
        if self.channel != "alerts" and not args.network_id:
            raise ValueError("Network channel requires network_id")
        if self.channel == "alerts" and args.network_id is not None:
            raise ValueError("Alerts cannot carry network_id")
        if (args.delta_type is not None) != (self.channel != "telemetry"):
            raise ValueError("Invalid delta_type for channel")
        return self

    def arguments(self) -> dict:
        assert self.kwargs is not None
        return self.kwargs.model_dump(exclude_none=True)

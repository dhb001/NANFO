"""Fixed, operator-versioned rules for persisted measured emulation observations."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictBool, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DetectorRule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: str = Field(default="operator-v1", pattern=r"^[a-zA-Z0-9_.-]{1,64}$")
    breach: float = Field(ge=0, allow_inf_nan=False)
    recover: float = Field(ge=0, allow_inf_nan=False)
    min_samples: int = Field(default=3, ge=3, le=10000, strict=True)
    duration_seconds: float = Field(default=10, ge=10, le=3600, allow_inf_nan=False)
    max_gap_seconds: float = Field(default=10, gt=0, le=60, allow_inf_nan=False)
    max_age_seconds: float = Field(default=30, gt=0, le=300, allow_inf_nan=False)

    @model_validator(mode="after")
    def hysteresis(self) -> Self:
        if self.recover >= self.breach:
            raise ValueError("recovery must be strictly below breach")
        return self


class DetectorSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ALERT_", extra="ignore", frozen=True)
    utilization: DetectorRule = DetectorRule(breach=85, recover=70)
    latency: DetectorRule = DetectorRule(breach=100, recover=70)
    loss: DetectorRule = DetectorRule(breach=2, recover=1)
    queue: DetectorRule = DetectorRule(breach=80, recover=40)


METRICS = {
    "link_utilization_percent": ("utilization", "%", "openflow_port_counter_delta"),
    "latency_ms": ("latency", "ms", "ping_rtt"),
    "packet_loss_percent": ("loss", "%", "ping_probe"),
    "queue_backlog_packets": ("queue", "packets", "linux_qdisc_backlog"),
}


class MeasuredTags(BaseModel):
    synthetic: StrictBool
    execution_mode: Literal["emulation"]
    quality: Literal["measured"]
    freshness: Literal["fresh"]
    run_id: uuid.UUID
    topology_id: Literal["campus-small-v1"]
    measurement_method: str
    port_no: int | None = Field(default=None, ge=1, le=2**32 - 1, strict=True)
    peer_host: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    dpid: str | None = Field(default=None, pattern=r"^[0-9a-f]{16}$")
    latency_semantics: str | None = None
    loss_semantics: str | None = None
    interval_seconds: float | None = Field(default=None, gt=0, le=86400, allow_inf_nan=False, strict=True)
    capacity_mbps: float | None = Field(default=None, gt=0, allow_inf_nan=False, strict=True)
    rate_quality: str | None = None


class MeasuredObservation(BaseModel):
    event_id: uuid.UUID
    correlation_id: uuid.UUID
    device_id: uuid.UUID
    network_id: uuid.UUID
    workspace_id: uuid.UUID
    metric: str
    value: float = Field(ge=0, allow_inf_nan=False, strict=True)
    unit: str
    source: Literal["emulation"]
    observed_at: AwareDatetime
    tags: MeasuredTags

    @model_validator(mode="after")
    def measured(self) -> Self:
        contract = METRICS.get(self.metric)
        tags = self.tags
        if (contract is None or tags.synthetic or self.unit != contract[1]
                or tags.measurement_method != contract[2]):
            raise ValueError("unsupported measured metric provenance or units")
        if contract[0] in {"utilization", "queue"}:
            if tags.port_no is None or tags.dpid is None or tags.peer_host is not None:
                raise ValueError("port metric needs an unambiguous port identity")
        elif tags.peer_host is None or tags.port_no is not None:
            raise ValueError("probe metric needs an unambiguous peer identity")
        if contract[0] == "utilization" and (
                tags.rate_quality != "measured" or tags.capacity_mbps is None or tags.interval_seconds is None):
            raise ValueError("utilization needs measured rate and known capacity")
        if contract[0] == "latency" and tags.latency_semantics != "RTT":
            raise ValueError("latency must be measured RTT")
        if contract[0] == "loss" and (tags.loss_semantics != "probe" or self.value > 100):
            raise ValueError("loss must be probe percent in 0..100")
        if contract[0] == "queue" and not self.value.is_integer():
            raise ValueError("packet backlog must be integral")
        self.observed_at = self.observed_at.astimezone(UTC)
        return self


def detector_identity(observation: MeasuredObservation, org_id: uuid.UUID, rule: DetectorRule) -> dict:
    return {
        "org_id": str(org_id), "workspace_id": str(observation.workspace_id),
        "network_id": str(observation.network_id), "device_id": str(observation.device_id),
        "port_no": observation.tags.port_no, "peer_host": observation.tags.peer_host,
        "run_id": str(observation.tags.run_id), "metric": observation.metric,
        "source": observation.source, "rule_version": rule.version,
    }


def identity_key(identity: dict) -> str:
    return hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def advance_window(state, observation: MeasuredObservation, rule: DetectorRule, *, now: datetime) -> bool:
    """Advance only strictly ordered, fresh samples; return sustained-phase readiness."""
    observed = observation.observed_at
    age = (now - observed).total_seconds()
    if age < 0 or age > rule.max_age_seconds:
        return False
    if state.last_observed_at is not None and observed <= state.last_observed_at:
        return False
    phase = "breach" if observation.value >= rule.breach else "recovery" if observation.value < rule.recover else None
    gap = (observed - state.last_observed_at).total_seconds() if state.last_observed_at else None
    if phase is None or state.phase != phase or gap is None or gap > rule.max_gap_seconds:
        state.phase, state.phase_since, state.sample_count = phase, observed if phase else None, 0
    state.sample_count += 1 if phase else 0
    state.last_observed_at, state.last_event_id = observed, observation.event_id
    return (phase is not None and state.sample_count >= rule.min_samples
            and (observed - state.phase_since).total_seconds() >= rule.duration_seconds)

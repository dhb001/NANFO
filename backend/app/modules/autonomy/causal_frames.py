"""Explicit causal-frame registration with reviewed envelopes, not measured maxima."""

from typing import Literal
import uuid
from fractions import Fraction
from ipaddress import IPv4Address

from pydantic import Field, model_serializer, model_validator

from app.modules.autonomy.schemas import SHA256, Contract, Observation, contract_digest
from app.modules.autonomy.safety import DemandObservation, QueueObservation, SafetyObservation
from app.modules.autonomy.provider_state import ProviderStateRepository


class CausalDemand(Contract):
    demand_id: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_]{0,30}$")
    source: str
    destination: str
    source_ipv4: IPv4Address
    destination_ipv4: IPv4Address
    ip_protocol: int = Field(strict=True, ge=0, le=255)
    enforced_lower_bytes_per_second: float = Field(ge=0)
    enforced_upper_bytes_per_second: float = Field(ge=0)


class CausalEgress(Contract):
    egress_id: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_]{0,30}$")
    node: str = Field(pattern=r"^[a-z][a-z0-9]{0,31}$")
    interface: str = Field(pattern=r"^[a-z][a-z0-9-]{0,31}$")
    source: str
    destination: str
    leaf_handle: str = Field(pattern=r"^[0-9a-f]+:$")
    capacity_bytes_per_second: float = Field(gt=0)
    shaper_nominal_bytes_per_second: float | None = Field(default=None, gt=0)
    measurement_error_bytes: float = Field(ge=0)


class CausalConfig(Contract):
    version: Literal["nanfo.frr-causal-instrument/v1", "nanfo.frr-causal-instrument/v2"]
    network_id: uuid.UUID
    workspace_id: uuid.UUID
    run_id: str
    runtime_binding_sha256: SHA256
    guarantee_sha256: SHA256
    configuration_sha256: SHA256
    window_seconds: float = Field(gt=0, le=30)
    clock_error_seconds: float = Field(gt=0, le=1)
    max_read_span_seconds: float = Field(gt=0, le=5)
    egresses: list[CausalEgress] = Field(min_length=1, max_length=256)
    demands: list[CausalDemand] = Field(min_length=1, max_length=256)

    @model_serializer(mode="wrap")
    def preserve_v1_instrument_digest(self, handler):
        result = handler(self)
        if self.version.endswith("/v1"):
            for egress in result["egresses"]:
                egress.pop("shaper_nominal_bytes_per_second", None)
        return result

    @model_validator(mode="after")
    def unique(self):
        if self.version.endswith("/v1") and any(e.shaper_nominal_bytes_per_second is not None for e in self.egresses):
            raise ValueError("causal_shaper_semantics_require_v2")
        if self.version.endswith("/v2") and any(e.shaper_nominal_bytes_per_second is None for e in self.egresses):
            raise ValueError("causal_v2_explicit_shaper_nominal_required")
        if (len({e.egress_id for e in self.egresses}) != len(self.egresses)
                or len({(e.node, e.interface) for e in self.egresses}) != len(self.egresses)
                or len({d.demand_id for d in self.demands}) != len(self.demands)
                or len({(d.source_ipv4, d.destination_ipv4, d.ip_protocol) for d in self.demands}) != len(self.demands)
                or any(d.demand_id == "unknown" or d.enforced_lower_bytes_per_second > d.enforced_upper_bytes_per_second for d in self.demands)):
            raise ValueError("causal_instrument_scope_invalid")
        return self


def safety_frame(config, capture, observation, *, sequence, accepted_guarantees, accepted_instruments):
    config = CausalConfig.model_validate(config)
    observation = Observation.model_validate(observation)
    metadata = capture
    v2 = config.version.endswith("/v2")
    if v2:
        from emulation.native_qualification_clock import causal_clock_binding, observation_datetime
        from emulation.native_qualification_causal import validate_ns_capture
        if capture.get("version") != "nanfo.frr-causal-envelope/v2":
            raise ValueError("causal_v2_envelope_required")
        capture = metadata["raw_capture"]
        binding = causal_clock_binding(capture)
        if (metadata.get("clock_binding") != binding
                or observation.observed_at != observation_datetime(binding)
                or "native-capture:" + binding["raw_capture_sha256"] not in observation.evidence
                or Fraction(binding["quantization_uncertainty_ns"], 10**9) > Fraction(config.clock_error_seconds)):
            raise ValueError("causal_native_clock_binding_mismatch")
        # Quantization moves the horizon back. Reserve error for bytes that could
        # depart between that boundary and the raw endpoint. This is additional
        # to read-skew/accounting obligations of the externally accepted instrument.
        quantization = Fraction(binding["quantization_uncertainty_ns"], 10**9)
        if any(Fraction(e.measurement_error_bytes) < Fraction(e.capacity_bytes_per_second) * quantization
               for e in config.egresses):
            raise ValueError("causal_quantization_error_not_covered")
        validate_ns_capture(capture, config.model_dump(mode="json"))
    if (contract_digest(config) not in accepted_instruments or config.guarantee_sha256 not in accepted_guarantees
            or capture.get("version") != ("nanfo.frr-causal-capture/v2" if v2 else "nanfo.frr-causal-capture/v1") or capture.get("failures")
            or capture.get("measurement_complete") is not True
            or metadata.get("observation_sha256") != contract_digest(observation)
            or metadata.get("instrument_sha256") != contract_digest(config)
            or metadata.get("runtime_binding_sha256") != config.runtime_binding_sha256
            or metadata.get("run_id") != config.run_id
            or config.network_id != observation.network_id or config.workspace_id != observation.workspace_id
            or observation.observed_at is None
            or (not v2 and capture["after"]["finished_unix"] != observation.observed_at.timestamp())):
        raise ValueError("causal_frame_not_attested_or_aligned")
    # Raw capture replay occurs before import via acquisition.validate_capture.
    from emulation.autonomous_causal import validate_capture
    if not v2:
        validate_capture(capture, config.model_dump(mode="json"))
    readings = {q["egress_id"]: q for q in capture["after"]["queues"]}
    return SafetyObservation(network_id=str(config.network_id), run_id=config.run_id,
        snapshot_id=contract_digest(observation), sequence=sequence,
        observed_at_unix_seconds=observation.observed_at.timestamp(), counter_reset=False,
        attribution_complete=True, unknown_demand_ids=[], queues=[QueueObservation(
            egress_id=e.egress_id, source=e.source, destination=e.destination,
            queue_bytes=float(readings[e.egress_id]["queue_bytes"]), capacity_bytes_per_second=e.capacity_bytes_per_second)
            for e in config.egresses], demands=[DemandObservation(demand_id=d.demand_id,
            source=d.source, destination=d.destination, arrival_lower_bytes_per_second=d.enforced_lower_bytes_per_second,
            arrival_upper_bytes_per_second=d.enforced_upper_bytes_per_second) for d in config.demands])


async def register_causal_frame(db, config, capture, observation, *, sequence, accepted_guarantees, accepted_instruments):
    frame = safety_frame(config, capture, observation, sequence=sequence,
        accepted_guarantees=accepted_guarantees, accepted_instruments=accepted_instruments)
    return await ProviderStateRepository(db).record_observation(observation, frame)

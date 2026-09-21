"""Offline ADR024 native design compiler and mathematical obligation checker.

This is tooling for a new, isolated kernel-queue campaign, not an installation
path. No native command is executed and no trusted evidence is manufactured.
"""

from __future__ import annotations

import argparse
import json
import math
from fractions import Fraction
from ipaddress import IPv4Address
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.autonomy.artifact_io import ArtifactStore
from app.modules.autonomy.safety import SafetyPolicy
from emulation.native_qualification import CATEGORIES, digest, queue_commands, regulator_transactions

Name = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,23}$")]
PositiveInt = Annotated[int, Field(strict=True, gt=0, le=2**31 - 1)]
Amount = Annotated[float, Field(ge=0, le=1e12, allow_inf_nan=False)]


class Strict(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", revalidate_instances="always")


class PacketBucket(Strict):
    packets_per_second: int = Field(strict=True, ge=1, le=1_000_000)
    burst_packets: int = Field(strict=True, ge=1, le=1_000_000)
    max_skb_bytes: int = Field(strict=True, ge=64, le=65535)

    def envelope(self):
        # nft packet limits use floor(unit_ns/rate) cost; nominal rate can
        # UNDERSTATE the implemented rate. No byte-limit rounding assumption.
        cost_ns = 1_000_000_000 // self.packets_per_second
        return (Fraction(self.burst_packets * self.max_skb_bytes),
                Fraction(1_000_000_000 * self.max_skb_bytes, cost_ns))


class NativeEgress(Strict):
    egress_id: Name
    node: Name
    peer: Name
    interface: str = Field(pattern=r"^[a-z][a-z0-9-]{0,14}$")
    queue_limit_bytes: PositiveInt
    shaper_bytes_per_second: PositiveInt
    shaper_burst_bytes: PositiveInt
    epoch_quota_bytes: PositiveInt | None = None
    buckets: dict[str, PacketBucket]

    @model_validator(mode="after")
    def scope(self):
        if set(self.buckets) != set(CATEGORIES) or self.node == self.peer:
            raise ValueError("native_complete_class_partition_required")
        maximum = max(b.max_skb_bytes for b in self.buckets.values())
        if min(self.shaper_burst_bytes, self.queue_limit_bytes) < maximum:
            raise ValueError("native_queue_or_shaper_cannot_accept_largest_packet")
        return self


class NativeDesign(Strict):
    version: Literal["nanfo.native-design/v1"]
    environment: Literal["isolated-emulation"]
    host_addresses: dict[str, str]
    egresses: list[NativeEgress] = Field(min_length=1, max_length=256)
    horizon_seconds: float = Field(gt=0, le=30, allow_inf_nan=False)
    minimum_window_seconds: float = Field(gt=0, le=30, allow_inf_nan=False)
    sensor_span_seconds: Amount
    clock_error_seconds: Amount
    # No scheduler latency inferred from measurements. None means NOT PROVED.
    prequeue_delay_upper_seconds: Amount | None
    sensor_error_bytes: Amount
    # Reviewed derivation needed for qdisc statistics / size accounting error.
    accounting_error_bytes: Amount

    @model_validator(mode="after")
    def scope(self):
        if set(self.host_addresses) != {"h1", "h2", "h3", "h4"}:
            raise ValueError("native_four_host_addresses_required")
        addresses = [str(IPv4Address(v)) for v in self.host_addresses.values()]
        if len(set(addresses)) != 4 or addresses != list(self.host_addresses.values()):
            raise ValueError("native_distinct_canonical_ipv4_required")
        if (len({e.egress_id for e in self.egresses}) != len(self.egresses)
                or len({(e.node, e.interface) for e in self.egresses}) != len(self.egresses)
                or self.minimum_window_seconds > self.horizon_seconds):
            raise ValueError("native_duplicate_scope_or_invalid_horizon")
        return self


def outward(value):
    result = float(value)
    if Fraction(result) < value:
        result = math.nextafter(result, math.inf)
    if not math.isfinite(result):
        raise ValueError("native_unrepresentable_bound")
    return result


def analyze(design, policy, queues):
    """Exact conditional feasibility; use the existing fixed policy, never fit it.

    q is the observed vector, as in SafetyShield. The raw collector does not
    establish sensor error, prequeue latency, timing or byte-unit equivalence.
    These remain obligations even if this arithmetic passes.
    """
    design = NativeDesign.model_validate(design)
    policy = SafetyPolicy.model_validate(policy)
    if set(queues) != {e.egress_id for e in design.egresses}:
        raise ValueError("native_queue_scope_mismatch")
    if any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in queues.values()):
        raise ValueError("native_invalid_queue_bytes")
    if design.horizon_seconds > policy.max_dt_seconds:
        raise ValueError("native_horizon_exceeds_fixed_policy")
    blockers, rows, drift = [], [], Fraction(0)
    if design.prequeue_delay_upper_seconds is None and any(e.epoch_quota_bytes is None for e in design.egresses):
        return {"arithmetic_passed": False, "activation_ready": False, "physical_qualified": False,
                "blockers": ["prequeue_delay_not_proved"], "queues": []}
    h = Fraction(design.horizon_seconds)
    skew = Fraction(design.sensor_span_seconds) + Fraction(design.clock_error_seconds)
    jitter = Fraction(design.prequeue_delay_upper_seconds or 0)
    for e in design.egresses:
        q = Fraction(queues[e.egress_id])
        sigma, rho = map(sum, zip(*(b.envelope() for b in e.buckets.values())))
        # A fixed rate is needed by the existing validator (it checks A <= a*dt
        # separately from E). Absorb burst over the MINIMUM acquisition window.
        if e.epoch_quota_bytes is not None:
            # Total epoch bytes includes all prequeue in-flight packets, regardless
            # of their delay. No reset, wrap, reinjection or pre-epoch backlog.
            a = Fraction(e.epoch_quota_bytes) / Fraction(design.minimum_window_seconds)
            error = Fraction(design.sensor_error_bytes) + Fraction(design.accounting_error_bytes)
        else:
            a = rho + (sigma + rho * jitter) / Fraction(design.minimum_window_seconds)
            error = (Fraction(design.sensor_error_bytes) + Fraction(design.accounting_error_bytes)
                     + sigma + rho * (skew + jitter))
        # The frozen shield does not clamp U to the physical queue limit.
        # The shield consumes serialized IEEE numbers. Compare exactly those
        # outward-rounded inputs, not the slightly smaller rational derivation.
        a, error = Fraction(outward(a)), Fraction(outward(error))
        upper = q + a * h + error
        increment = (upper * upper - q * q) / 2
        drift += increment
        if q > e.queue_limit_bytes:
            blockers.append("observed_queue_exceeds_kernel_limit:" + e.egress_id)
        if max(q, upper) > Fraction(policy.queue_threshold_bytes):
            blockers.append("queue_threshold_failed:" + e.egress_id)
        # A cap-derived bound that already exceeds L adds no safety knowledge.
        rows.append({"egress_id": e.egress_id, "sigma_bytes": outward(sigma),
                     "rho_bytes_per_second": outward(rho),
                     "arrival_upper_bytes_per_second": outward(a),
                     "service_lower_bytes_per_second": 0.0,
                     "error_upper_bytes": outward(error), "q_next_upper_bytes": outward(upper),
                     "strictly_tighter_than_queue_cap": upper < e.queue_limit_bytes,
                     "arrival_basis": "finite-epoch-quota" if e.epoch_quota_bytes else "bounded-prequeue-delay",
                     "queue_limit_bytes": e.queue_limit_bytes})
    if drift > Fraction(policy.drift_budget_bytes_squared):
        blockers.append("fixed_drift_budget_failed")
    if not any(row["strictly_tighter_than_queue_cap"] for row in rows):
        blockers.append("cap_only_tautology")
    return {"version": "nanfo.native-obligations/v1", "arithmetic_passed": not blockers,
            "activation_ready": False, "physical_qualified": False, "queues": rows,
            "drift_upper_bytes_squared": outward(drift),
            "fixed_budget_bytes_squared": policy.drift_budget_bytes_squared,
            "policy_sha256": digest(policy.model_dump(mode="json")), "blockers": blockers,
            "unproved_obligations": ["running_kernel_source_equivalence", "prequeue_delay_or_fresh_nonrenewable_quota_epoch",
                "all_egresses_no_bypass", "skb_qdisc_byte_equivalence", "sensor_error_derivation",
                "service_upper_includes_shaper_burst", "route_transition_union",
                "exclusive_handoff", "hard_dispatch_completion_timing", "independent_measured_campaign"]}


def preregistered_schedule(prefix, seeds):
    """Whole-session train/holdout groups; no data-dependent seed/row selection."""
    if (len(seeds) != 6 or len(set(seeds)) != 6
            or any(type(seed) is not int or not 0 <= seed < 2**32 for seed in seeds)):
        raise ValueError("native_six_distinct_session_seeds_required")
    # start at baseline0; receiver can 0->1 then recover1->0; holds are measured
    # without pretending driver.prepare supports installing over an active override.
    transitions = [(0, 0), (0, 1), (1, 1), (1, 0)] * 2
    return [{"group_id": f"{prefix}-{i}", "split": "train" if i < 3 else "holdout",
             "seed": seed, "samples": [
                 {"sample_id": f"{prefix}-{i}-{j}", "previous_action": old, "action": new,
                  "load": "sustained" if j < 4 else "admitted-burst"}
                 for j, (old, new) in enumerate(transitions)]} for i, seed in enumerate(seeds)]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", action="store_true")
    parser.add_argument("--root")
    parser.add_argument("--design")
    parser.add_argument("--design-sha256")
    parser.add_argument("--policy")
    parser.add_argument("--policy-sha256")
    parser.add_argument("--queues")
    args = parser.parse_args(argv)
    if args.schema:
        print(json.dumps(NativeDesign.model_json_schema(), sort_keys=True))
        return 0
    if not all((args.root, args.design, args.design_sha256, args.policy, args.policy_sha256, args.queues)):
        parser.error("supply pinned design/policy and observed-or-explicit-design queue vector")
    try:
        store = ArtifactStore(args.root)
        design = NativeDesign.model_validate(store.document(args.design, sha256=args.design_sha256))
        policy = SafetyPolicy.model_validate(store.document(args.policy, sha256=args.policy_sha256))
        report = analyze(design, policy, store.document(args.queues))
        spec = design.model_dump(mode="json")
        report.update(nft_transactions=regulator_transactions(spec), tc_commands=queue_commands(spec))
    except (ValueError, OSError, OverflowError):
        print(json.dumps({"activation_ready": False, "error": "invalid_native_design_or_pin"}))
        return 2
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 0 if report["arithmetic_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

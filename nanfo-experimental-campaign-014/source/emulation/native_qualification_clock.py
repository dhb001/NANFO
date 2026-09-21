"""Exact native-nanosecond -> observation boundary, without modifying raw bytes.

Datetime supports microseconds. Floor UTC to a microsecond, then (if binary float
timestamp rounds into the future) move one more microsecond back. Both identities
and an outward-rounded TOTAL quantization error are bound to the original capture.
This is not a license to align an independently acquired model observation.
"""

import math
from datetime import UTC, datetime, timedelta
from fractions import Fraction

from emulation.native_qualification import digest

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def canonical_observation_clock(raw_capture, *, finished_wall_ns, finished_monotonic_ns):
    for value in (finished_wall_ns, finished_monotonic_ns):
        if type(value) is not int or not 0 <= value < 2**63:
            raise ValueError("native_integer_clock_required")
    exact = Fraction(finished_wall_ns, 10**9)
    observed = EPOCH + timedelta(microseconds=finished_wall_ns // 1000)
    if Fraction(observed.timestamp()) > exact:
        observed -= timedelta(microseconds=1)
    seconds = observed.timestamp()
    us = ((observed - EPOCH).days * 86400 + (observed - EPOCH).seconds) * 10**6 + observed.microsecond
    error = max(exact - Fraction(seconds), exact - Fraction(us, 10**6))
    uncertainty_ns = math.ceil(error * 10**9)
    return {"version": "nanfo.native-observation-clock/v1", "raw_capture_sha256": digest(raw_capture),
            "finished_wall_ns": finished_wall_ns, "finished_monotonic_ns": finished_monotonic_ns,
            "observed_at": observed.isoformat(timespec="microseconds"),
            "observed_at_unix_seconds": seconds, "quantization_uncertainty_ns": uncertainty_ns,
            "rule": "utc-microsecond-floor-and-nonfuture-binary64"}


def causal_clock_binding(raw_capture):
    endpoint = raw_capture["after"]
    return canonical_observation_clock(raw_capture, finished_wall_ns=endpoint["finished_wall_ns"],
                                       finished_monotonic_ns=endpoint["finished_monotonic_ns"])


def endpoint_clock_binding(raw_capture):
    # Native bfifo collector's last completed read, not a new wall-clock sample.
    row = raw_capture["reads"][-1]
    return canonical_observation_clock(raw_capture, finished_wall_ns=row["end_wall_ns"],
                                       finished_monotonic_ns=row["end_monotonic_ns"])


def observation_datetime(binding):
    return datetime.fromisoformat(binding["observed_at"])

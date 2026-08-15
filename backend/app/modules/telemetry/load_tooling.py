"""VS17 external load-tooling helpers for telemetry continuity execution."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import redis.asyncio as aioredis

from app.core.logging import get_logger
from app.modules.telemetry.service import TelemetryIngestionService

logger = get_logger(__name__)

VS17_K6_DOCKER_IMAGE = "grafana/k6:0.57.0"
VS17_ARTIFACT_VERSION = "vs17.external-load.v1"
VS17_DEFAULT_ARTIFACT_DIR = Path("artifacts/load-testing/vs17")
VS17_DEFAULT_K6_SCRIPT_PATH = Path("scripts/k6/vs17_telemetry_health.js")

VS18_BASELINE_LOCAL_SMOKE_HTTP_REQ_FAILED_RATE = 0.0
VS18_BASELINE_LOCAL_SMOKE_HTTP_REQ_DURATION_P95_MS = 2.1907872
VS18_BASELINE_LOCAL_SMOKE_EVENTS = 120

VS18_MAX_HTTP_REQ_FAILED_RATE = 0.05
VS18_MAX_HTTP_REQ_DURATION_P95_MS = 500.0
VS18_MIN_PERSIST_TO_PUBLISHED_RATIO = 0.99
VS18_MIN_FANOUT_TO_PUBLISHED_RATIO = 0.99
VS18_MAX_DROPPED_TO_PUBLISHED_RATIO = 0.01

VS17_EVIDENCE_COUNTER_KEYS = (
    "ingested_events",
    "persisted_events",
    "fanout_events",
    "dropped_events",
)


@dataclass(frozen=True)
class VS17LoadProfile:
    """Deterministic external load profile for VS17 continuity runs."""

    name: str
    k6_vus: int
    k6_duration: str
    k6_sleep_seconds: float
    fixture_events: int
    fixture_sleep_seconds: float = 0.0
    fixture_metric_sequence: tuple[str, ...] = (
        "latency_ms",
        "packet_loss",
        "throughput_mbps",
    )

    @property
    def slug(self) -> str:
        return self.name.replace("-", "_")


@dataclass(frozen=True)
class VS17FixturePumpResult:
    """Synthetic fixture publish result for deterministic VS17 evidence."""

    events_requested: int
    events_published: int
    publish_failures: int
    first_correlation_id: str | None
    last_correlation_id: str | None


@dataclass(frozen=True)
class VS17CommandResult:
    """Result for external load command execution."""

    exit_code: int
    stdout: str
    stderr: str


VS17_LOAD_PROFILES: dict[str, VS17LoadProfile] = {
    "local-smoke": VS17LoadProfile(
        name="local-smoke",
        k6_vus=5,
        k6_duration="20s",
        k6_sleep_seconds=0.2,
        fixture_events=120,
    ),
    "local-burst": VS17LoadProfile(
        name="local-burst",
        k6_vus=20,
        k6_duration="45s",
        k6_sleep_seconds=0.1,
        fixture_events=600,
    ),
    "staging-baseline": VS17LoadProfile(
        name="staging-baseline",
        k6_vus=40,
        k6_duration="120s",
        k6_sleep_seconds=0.05,
        fixture_events=2000,
    ),
}


def list_vs17_load_profiles() -> tuple[str, ...]:
    return tuple(VS17_LOAD_PROFILES.keys())


def get_vs17_load_profile(name: str) -> VS17LoadProfile:
    profile = VS17_LOAD_PROFILES.get(name)
    if profile is None:
        raise ValueError(f"Unknown VS17 load profile: {name!r}")
    return profile


def resolve_vs17_k6_runner(
    mode: str = "auto",
    *,
    k6_lookup: Callable[[str], str | None] = shutil.which,
    docker_lookup: Callable[[str], str | None] = shutil.which,
) -> Literal["host", "docker"]:
    """Resolve the k6 execution path (host binary or Docker fallback)."""
    normalized_mode = mode.strip().lower()
    if normalized_mode not in {"auto", "host", "docker"}:
        raise ValueError("k6 mode must be one of: auto, host, docker")

    if normalized_mode == "host":
        if k6_lookup("k6"):
            return "host"
        raise RuntimeError("k6 host runner requested but `k6` binary was not found")

    if normalized_mode == "docker":
        if docker_lookup("docker"):
            return "docker"
        raise RuntimeError("k6 docker runner requested but `docker` binary was not found")

    if k6_lookup("k6"):
        return "host"
    if docker_lookup("docker"):
        return "docker"
    raise RuntimeError("No k6 runner available; install `k6` or ensure Docker is available")


def build_vs17_summary_path(*, output_dir: Path, run_id: str, profile: VS17LoadProfile) -> Path:
    return output_dir / f"{run_id}_{profile.slug}_k6_summary.json"


def build_vs17_k6_command(
    *,
    runner: Literal["host", "docker"],
    profile: VS17LoadProfile,
    script_path: Path,
    summary_path: Path,
    base_url: str,
    auth_token: str | None = None,
) -> list[str]:
    """Build deterministic k6 command for host or Docker execution modes."""
    if not script_path.exists():
        raise FileNotFoundError(f"k6 script file not found: {script_path}")

    env_args = [
        "--env",
        f"NANFO_BASE_URL={base_url}",
        "--env",
        f"VS17_VUS={profile.k6_vus}",
        "--env",
        f"VS17_DURATION={profile.k6_duration}",
        "--env",
        f"VS17_SLEEP_SECONDS={profile.k6_sleep_seconds}",
    ]
    if auth_token:
        env_args.extend(["--env", f"NANFO_AUTH_TOKEN={auth_token}"])

    if runner == "host":
        return [
            "k6",
            "run",
            *env_args,
            "--summary-export",
            str(summary_path),
            str(script_path),
        ]

    script_dir = script_path.resolve().parent
    summary_dir = summary_path.resolve().parent
    container_script_path = f"/scripts/{script_path.name}"
    container_summary_path = f"/artifacts/{summary_path.name}"
    return [
        "docker",
        "run",
        "--rm",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--network",
        "host",
        "-v",
        f"{script_dir}:/scripts:ro",
        "-v",
        f"{summary_dir}:/artifacts",
        VS17_K6_DOCKER_IMAGE,
        "run",
        *env_args,
        "--summary-export",
        container_summary_path,
        container_script_path,
    ]


def build_vs17_deterministic_sample(*, profile: VS17LoadProfile, index: int) -> dict[str, object]:
    """Build a deterministic telemetry sample used by VS17 fixture pumping."""
    metric = profile.fixture_metric_sequence[index % len(profile.fixture_metric_sequence)]
    observed_at = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(milliseconds=index * 250)
    seed = f"vs17:{profile.name}:{index}"
    return {
        "device_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{seed}:device")),
        "network_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{seed}:network")),
        "workspace_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{seed}:workspace")),
        "metric": metric,
        "value": _deterministic_metric_value(metric=metric, index=index),
        "unit": _deterministic_metric_unit(metric=metric),
        "observed_at": observed_at.isoformat(),
        "source": "vs17_external_load",
        "tags": {
            "campaign": "vs17_external_load",
            "profile": profile.name,
            "sample_index": str(index),
        },
    }


def _deterministic_metric_value(*, metric: str, index: int) -> float:
    if metric == "latency_ms":
        return float(10 + (index % 9))
    if metric == "packet_loss":
        return round((index % 5) * 0.01, 4)
    if metric == "throughput_mbps":
        return float(200 + ((index % 8) * 10))
    return float(index % 100)


def _deterministic_metric_unit(*, metric: str) -> str:
    if metric == "packet_loss":
        return "ratio"
    if metric == "throughput_mbps":
        return "mbps"
    return "ms"


async def pump_vs17_synthetic_fixture(
    *,
    redis: aioredis.Redis,
    profile: VS17LoadProfile,
    correlation_seed: str = "vs17-fixture",
) -> VS17FixturePumpResult:
    """Publish deterministic synthetic telemetry events for VS17 load evidence."""
    ingestion = TelemetryIngestionService(redis=redis)

    events_requested = profile.fixture_events
    events_published = 0
    publish_failures = 0
    first_correlation_id: str | None = None
    last_correlation_id: str | None = None

    for index in range(events_requested):
        sample = build_vs17_deterministic_sample(profile=profile, index=index)
        correlation_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"{correlation_seed}:{profile.name}:{index}",
            )
        )
        try:
            await ingestion.ingest(raw=sample, correlation_id=correlation_id)
            events_published += 1
            if first_correlation_id is None:
                first_correlation_id = correlation_id
            last_correlation_id = correlation_id
        except Exception as exc:  # noqa: BLE001
            publish_failures += 1
            logger.warning(
                "vs17_fixture_publish_failed",
                profile=profile.name,
                sample_index=index,
                correlation_id=correlation_id,
                error=str(exc),
            )

        if profile.fixture_sleep_seconds > 0:
            await asyncio.sleep(profile.fixture_sleep_seconds)

    return VS17FixturePumpResult(
        events_requested=events_requested,
        events_published=events_published,
        publish_failures=publish_failures,
        first_correlation_id=first_correlation_id,
        last_correlation_id=last_correlation_id,
    )


def build_vs17_counter_delta(
    *,
    counters_before: dict[str, int],
    counters_after: dict[str, int],
) -> dict[str, int]:
    """Compute key counter deltas used for VS17 acceptance evidence."""
    delta: dict[str, int] = {}
    for key in VS17_EVIDENCE_COUNTER_KEYS:
        before_value = _to_int(counters_before.get(key, 0))
        after_value = _to_int(counters_after.get(key, 0))
        delta[key] = after_value - before_value
    return delta


def load_vs17_k6_summary(summary_path: Path) -> dict[str, Any] | None:
    """Load optional k6 summary JSON generated by --summary-export."""
    if not summary_path.exists():
        return None

    try:
        return json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("vs17_k6_summary_read_failed", path=str(summary_path), error=str(exc))
        return None


def extract_vs17_k6_metrics(summary: dict[str, Any] | None) -> dict[str, float | None]:
    """Extract stable signal metrics from k6 summary output."""
    if not isinstance(summary, dict):
        return {
            "http_req_failed_rate": None,
            "http_req_duration_p95_ms": None,
            "http_reqs_count": None,
        }

    metrics = summary.get("metrics")
    if not isinstance(metrics, dict):
        return {
            "http_req_failed_rate": None,
            "http_req_duration_p95_ms": None,
            "http_reqs_count": None,
        }

    return {
        "http_req_failed_rate": _extract_k6_metric_value(metrics, "http_req_failed", "rate"),
        "http_req_duration_p95_ms": _extract_k6_metric_from_candidates(
            metrics,
            ("http_req_duration", "http_req_duration{expected_response:true}"),
            "p(95)",
        ),
        "http_reqs_count": _extract_k6_metric_value(metrics, "http_reqs", "count"),
    }


def evaluate_vs18_continuity_posture(
    *,
    fixture_result: VS17FixturePumpResult,
    counter_delta: dict[str, int],
    k6_metrics: dict[str, float | None],
    k6_metrics_required: bool,
) -> dict[str, Any]:
    """Evaluate VS18 continuity thresholds using VS17 evidence signals."""
    published_events = max(_to_int(fixture_result.events_published), 0)
    ratio_denominator = max(published_events, 1)

    persisted_events = _to_int(counter_delta.get("persisted_events", 0))
    fanout_events = _to_int(counter_delta.get("fanout_events", 0))
    dropped_events = _to_int(counter_delta.get("dropped_events", 0))

    persisted_ratio = persisted_events / ratio_denominator
    fanout_ratio = fanout_events / ratio_denominator
    dropped_ratio = dropped_events / ratio_denominator

    http_req_failed_rate = _to_optional_float(k6_metrics.get("http_req_failed_rate"))
    http_req_duration_p95_ms = _to_optional_float(k6_metrics.get("http_req_duration_p95_ms"))

    checks = {
        "persist_ratio_within_threshold": persisted_ratio >= VS18_MIN_PERSIST_TO_PUBLISHED_RATIO,
        "fanout_ratio_within_threshold": fanout_ratio >= VS18_MIN_FANOUT_TO_PUBLISHED_RATIO,
        "dropped_ratio_within_threshold": dropped_ratio <= VS18_MAX_DROPPED_TO_PUBLISHED_RATIO,
    }

    if k6_metrics_required:
        checks["http_req_failed_rate_within_threshold"] = (
            http_req_failed_rate is not None
            and http_req_failed_rate <= VS18_MAX_HTTP_REQ_FAILED_RATE
        )
        checks["http_req_duration_p95_within_threshold"] = (
            http_req_duration_p95_ms is not None
            and http_req_duration_p95_ms <= VS18_MAX_HTTP_REQ_DURATION_P95_MS
        )
    else:
        checks["http_req_failed_rate_within_threshold"] = True
        checks["http_req_duration_p95_within_threshold"] = True

    return {
        "baseline": {
            "source": "vs17_local_smoke_20260814T205740Z",
            "http_req_failed_rate": VS18_BASELINE_LOCAL_SMOKE_HTTP_REQ_FAILED_RATE,
            "http_req_duration_p95_ms": VS18_BASELINE_LOCAL_SMOKE_HTTP_REQ_DURATION_P95_MS,
            "fixture_events": VS18_BASELINE_LOCAL_SMOKE_EVENTS,
            "counter_delta": {
                "ingested_events": VS18_BASELINE_LOCAL_SMOKE_EVENTS,
                "persisted_events": VS18_BASELINE_LOCAL_SMOKE_EVENTS,
                "fanout_events": VS18_BASELINE_LOCAL_SMOKE_EVENTS,
                "dropped_events": 0,
            },
        },
        "thresholds": {
            "max_http_req_failed_rate": VS18_MAX_HTTP_REQ_FAILED_RATE,
            "max_http_req_duration_p95_ms": VS18_MAX_HTTP_REQ_DURATION_P95_MS,
            "min_persist_to_published_ratio": VS18_MIN_PERSIST_TO_PUBLISHED_RATIO,
            "min_fanout_to_published_ratio": VS18_MIN_FANOUT_TO_PUBLISHED_RATIO,
            "max_dropped_to_published_ratio": VS18_MAX_DROPPED_TO_PUBLISHED_RATIO,
        },
        "observed": {
            "published_events": published_events,
            "persisted_events": persisted_events,
            "fanout_events": fanout_events,
            "dropped_events": dropped_events,
            "persist_to_published_ratio": round(persisted_ratio, 6),
            "fanout_to_published_ratio": round(fanout_ratio, 6),
            "dropped_to_published_ratio": round(dropped_ratio, 6),
            "http_req_failed_rate": http_req_failed_rate,
            "http_req_duration_p95_ms": http_req_duration_p95_ms,
            "k6_metrics_required": k6_metrics_required,
        },
        "checks": checks,
    }


def _extract_k6_metric_from_candidates(
    metrics: dict[str, Any],
    metric_names: tuple[str, ...],
    field_name: str,
) -> float | None:
    for metric_name in metric_names:
        value = _extract_k6_metric_value(metrics, metric_name, field_name)
        if value is not None:
            return value
    return None


def _extract_k6_metric_value(
    metrics: dict[str, Any],
    metric_name: str,
    field_name: str,
) -> float | None:
    metric_entry = metrics.get(metric_name)
    if not isinstance(metric_entry, dict):
        return None

    raw_value: Any | None = None
    values = metric_entry.get("values")
    if not isinstance(values, dict):
        raw_value = metric_entry.get(field_name)
    else:
        raw_value = values.get(field_name)
        if raw_value is None:
            raw_value = metric_entry.get(field_name)

    if raw_value is None and field_name == "rate":
        raw_value = metric_entry.get("value")

    if raw_value is None:
        return None
    try:
        return float(raw_value)
    except (TypeError, ValueError):
        return None


def run_vs17_command(command: list[str], *, timeout_seconds: int) -> VS17CommandResult:
    """Execute an external command with timeout handling for VS17 tooling."""
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        return VS17CommandResult(
            exit_code=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
        )
    except subprocess.TimeoutExpired as exc:
        stdout = _coerce_process_output(exc.stdout)
        stderr = _coerce_process_output(exc.stderr)
        return VS17CommandResult(exit_code=124, stdout=stdout, stderr=stderr)


def _coerce_process_output(raw: bytes | str | None) -> str:
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    return raw


def build_vs17_evidence_payload(
    *,
    run_id: str,
    profile: VS17LoadProfile,
    k6_runner: str,
    k6_command: list[str],
    k6_result: VS17CommandResult | None,
    k6_summary: dict[str, Any] | None,
    fixture_result: VS17FixturePumpResult,
    counters_before: dict[str, int],
    counters_after: dict[str, int],
    started_at: datetime,
    finished_at: datetime,
    failure_reason: str | None = None,
) -> dict[str, Any]:
    """Build canonical VS17 evidence payload for deterministic artifact output."""
    counter_delta = build_vs17_counter_delta(
        counters_before=counters_before,
        counters_after=counters_after,
    )
    k6_metrics = extract_vs17_k6_metrics(k6_summary)
    continuity = evaluate_vs18_continuity_posture(
        fixture_result=fixture_result,
        counter_delta=counter_delta,
        k6_metrics=k6_metrics,
        k6_metrics_required=k6_runner != "skipped",
    )
    continuity_checks = continuity["checks"]

    k6_exit_code = k6_result.exit_code if k6_result is not None else None
    acceptance_checks = {
        "fixture_publish_complete": fixture_result.events_published
        == fixture_result.events_requested,
        "ingest_signal_present": counter_delta["ingested_events"] >= fixture_result.events_published,
        "persist_signal_present": counter_delta["persisted_events"] > 0,
        "fanout_signal_present": counter_delta["fanout_events"] > 0,
        "error_signal_recorded": counter_delta["dropped_events"] >= 0,
        "k6_command_success": k6_exit_code in (None, 0),
        "continuity_http_req_failed_rate_within_threshold": continuity_checks[
            "http_req_failed_rate_within_threshold"
        ],
        "continuity_http_req_duration_p95_within_threshold": continuity_checks[
            "http_req_duration_p95_within_threshold"
        ],
        "continuity_persist_ratio_within_threshold": continuity_checks[
            "persist_ratio_within_threshold"
        ],
        "continuity_fanout_ratio_within_threshold": continuity_checks[
            "fanout_ratio_within_threshold"
        ],
        "continuity_dropped_ratio_within_threshold": continuity_checks[
            "dropped_ratio_within_threshold"
        ],
    }
    is_success = failure_reason is None and all(acceptance_checks.values())

    return {
        "artifact_version": VS17_ARTIFACT_VERSION,
        "run_id": run_id,
        "status": "success" if is_success else "failed",
        "profile": asdict(profile),
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_seconds": round((finished_at - started_at).total_seconds(), 3),
        "k6": {
            "runner": k6_runner,
            "command": k6_command,
            "exit_code": k6_exit_code,
            "stdout": _truncate_text(k6_result.stdout if k6_result else ""),
            "stderr": _truncate_text(k6_result.stderr if k6_result else ""),
            "metrics": k6_metrics,
        },
        "continuity": continuity,
        "fixture": asdict(fixture_result),
        "counters": {
            "before": counters_before,
            "after": counters_after,
            "delta": counter_delta,
        },
        "evidence": {
            "ingest_events": counter_delta["ingested_events"],
            "persist_events": counter_delta["persisted_events"],
            "fanout_events": counter_delta["fanout_events"],
            "error_events": counter_delta["dropped_events"],
        },
        "acceptance_checks": acceptance_checks,
        "failure_reason": failure_reason,
    }


def write_vs17_evidence_artifact(
    *,
    evidence_payload: dict[str, Any],
    output_dir: Path,
    run_id: str,
    profile: VS17LoadProfile,
) -> Path:
    """Write VS17 evidence artifact to a deterministic JSON file path."""
    output_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = output_dir / f"{run_id}_{profile.slug}.json"
    artifact_path.write_text(
        f"{json.dumps(evidence_payload, indent=2, sort_keys=True)}\n",
        encoding="utf-8",
    )
    return artifact_path


def _truncate_text(value: str, limit: int = 4000) -> str:
    if len(value) <= limit:
        return value
    return f"{value[:limit]}\n...<truncated>"


def _to_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _to_optional_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None

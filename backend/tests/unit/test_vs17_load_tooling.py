"""Unit tests for VS17 external load-tooling helpers."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.modules.telemetry.load_tooling import (
    VS17_LOAD_PROFILES,
    VS17FixturePumpResult,
    VS17LoadProfile,
    build_vs17_counter_delta,
    build_vs17_deterministic_sample,
    build_vs17_evidence_payload,
    build_vs17_k6_command,
    build_vs17_summary_path,
    extract_vs17_k6_metrics,
    get_vs17_load_profile,
    list_vs17_load_profiles,
    load_vs17_k6_summary,
    pump_vs17_synthetic_fixture,
    resolve_vs17_k6_runner,
    run_vs17_command,
    write_vs17_evidence_artifact,
)
from scripts.run_vs17_external_load import _resolve_writable_output_dir


def _fixture_profile() -> VS17LoadProfile:
    return VS17LoadProfile(
        name="local-smoke",
        k6_vus=5,
        k6_duration="20s",
        k6_sleep_seconds=0.2,
        fixture_events=3,
    )


def test_list_profiles_returns_expected_keys():
    assert set(list_vs17_load_profiles()) == set(VS17_LOAD_PROFILES.keys())


def test_get_profile_returns_profile():
    profile = get_vs17_load_profile("local-smoke")
    assert profile.name == "local-smoke"
    assert profile.fixture_events == 120


def test_get_profile_raises_for_unknown():
    with pytest.raises(ValueError, match="Unknown VS17 load profile"):
        get_vs17_load_profile("unknown")


def test_resolve_k6_runner_prefers_host_in_auto_mode():
    runner = resolve_vs17_k6_runner(
        "auto",
        k6_lookup=lambda cmd: "/usr/bin/k6" if cmd == "k6" else None,
        docker_lookup=lambda cmd: "/usr/bin/docker" if cmd == "docker" else None,
    )
    assert runner == "host"


def test_resolve_k6_runner_uses_docker_fallback_in_auto_mode():
    runner = resolve_vs17_k6_runner(
        "auto",
        k6_lookup=lambda _cmd: None,
        docker_lookup=lambda cmd: "/usr/bin/docker" if cmd == "docker" else None,
    )
    assert runner == "docker"


def test_resolve_k6_runner_raises_when_no_runner_available():
    with pytest.raises(RuntimeError, match="No k6 runner available"):
        resolve_vs17_k6_runner(
            "auto",
            k6_lookup=lambda _cmd: None,
            docker_lookup=lambda _cmd: None,
        )


def test_build_summary_path_is_deterministic(tmp_path: Path):
    profile = _fixture_profile()
    path = build_vs17_summary_path(output_dir=tmp_path, run_id="20260814T120000Z", profile=profile)
    assert path == tmp_path / "20260814T120000Z_local_smoke_k6_summary.json"


def test_build_k6_command_host_mode(tmp_path: Path):
    profile = _fixture_profile()
    script = tmp_path / "vs17.js"
    script.write_text("export default function() {}\n", encoding="utf-8")
    summary = tmp_path / "summary.json"

    command = build_vs17_k6_command(
        runner="host",
        profile=profile,
        script_path=script,
        summary_path=summary,
        base_url="http://127.0.0.1:8000",
        auth_token="token-123",
    )

    assert command[0:2] == ["k6", "run"]
    assert "NANFO_BASE_URL=http://127.0.0.1:8000" in command
    assert "VS17_VUS=5" in command
    assert "VS17_DURATION=20s" in command
    assert "VS17_SLEEP_SECONDS=0.2" in command
    assert "NANFO_AUTH_TOKEN=token-123" in command
    assert command[-2:] == [str(summary), str(script)]


def test_build_k6_command_docker_mode(tmp_path: Path):
    profile = _fixture_profile()
    script_dir = tmp_path / "scripts"
    script_dir.mkdir(parents=True, exist_ok=True)
    script = script_dir / "vs17.js"
    script.write_text("export default function() {}\n", encoding="utf-8")
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    summary = artifact_dir / "summary.json"

    command = build_vs17_k6_command(
        runner="docker",
        profile=profile,
        script_path=script,
        summary_path=summary,
        base_url="http://127.0.0.1:8000",
    )

    assert command[0:3] == ["docker", "run", "--rm"]
    assert "--network" in command
    assert "host" in command
    assert "grafana/k6:0.57.0" in command
    assert "/scripts/vs17.js" in command
    assert "/artifacts/summary.json" in command


def test_build_k6_command_raises_if_script_missing(tmp_path: Path):
    profile = _fixture_profile()
    with pytest.raises(FileNotFoundError, match="k6 script file not found"):
        build_vs17_k6_command(
            runner="host",
            profile=profile,
            script_path=tmp_path / "missing.js",
            summary_path=tmp_path / "summary.json",
            base_url="http://127.0.0.1:8000",
        )


def test_build_deterministic_sample_is_reproducible():
    profile = _fixture_profile()
    sample_a = build_vs17_deterministic_sample(profile=profile, index=2)
    sample_b = build_vs17_deterministic_sample(profile=profile, index=2)
    sample_c = build_vs17_deterministic_sample(profile=profile, index=3)

    assert sample_a == sample_b
    assert sample_a["device_id"] != sample_c["device_id"]
    assert sample_a["source"] == "vs17_external_load"
    assert sample_a["tags"]["profile"] == profile.name


@pytest.mark.asyncio
async def test_pump_synthetic_fixture_publishes_expected_count(fake_redis):
    profile = _fixture_profile()

    result = await pump_vs17_synthetic_fixture(redis=fake_redis, profile=profile)

    assert result.events_requested == 3
    assert result.events_published == 3
    assert result.publish_failures == 0
    assert result.first_correlation_id is not None
    assert result.last_correlation_id is not None


@pytest.mark.asyncio
async def test_pump_synthetic_fixture_tracks_publish_failures(fake_redis):
    profile = _fixture_profile()

    with patch(
        "app.modules.telemetry.load_tooling.TelemetryIngestionService.ingest",
        new=AsyncMock(side_effect=[None, RuntimeError("publish failed"), None]),
    ):
        result = await pump_vs17_synthetic_fixture(redis=fake_redis, profile=profile)

    assert result.events_requested == 3
    assert result.events_published == 2
    assert result.publish_failures == 1


def test_build_counter_delta_computes_expected_values():
    before = {
        "ingested_events": 10,
        "persisted_events": 9,
        "fanout_events": 9,
        "dropped_events": 1,
    }
    after = {
        "ingested_events": 40,
        "persisted_events": 35,
        "fanout_events": 33,
        "dropped_events": 2,
    }

    delta = build_vs17_counter_delta(counters_before=before, counters_after=after)

    assert delta == {
        "ingested_events": 30,
        "persisted_events": 26,
        "fanout_events": 24,
        "dropped_events": 1,
    }


def test_load_k6_summary_reads_valid_json(tmp_path: Path):
    summary_path = tmp_path / "summary.json"
    summary_path.write_text('{"metrics": {"http_reqs": {"values": {"count": 10}}}}', encoding="utf-8")
    summary = load_vs17_k6_summary(summary_path)
    assert summary is not None
    assert summary["metrics"]["http_reqs"]["values"]["count"] == 10


def test_load_k6_summary_returns_none_for_missing_file(tmp_path: Path):
    assert load_vs17_k6_summary(tmp_path / "missing.json") is None


def test_extract_k6_metrics_handles_missing_payloads():
    metrics = extract_vs17_k6_metrics(None)
    assert metrics == {
        "http_req_failed_rate": None,
        "http_req_duration_p95_ms": None,
        "http_reqs_count": None,
    }


def test_extract_k6_metrics_reads_expected_fields():
    summary = {
        "metrics": {
            "http_req_failed": {"values": {"rate": 0.01}},
            "http_req_duration": {"values": {"p(95)": 210.5}},
            "http_reqs": {"values": {"count": 800}},
        }
    }
    metrics = extract_vs17_k6_metrics(summary)
    assert metrics == {
        "http_req_failed_rate": 0.01,
        "http_req_duration_p95_ms": 210.5,
        "http_reqs_count": 800.0,
    }


def test_extract_k6_metrics_supports_k6_flat_metric_shape():
    summary = {
        "metrics": {
            "http_req_failed": {"value": 0.0},
            "http_req_duration": {"p(95)": 2.05},
            "http_reqs": {"count": 500},
        }
    }

    metrics = extract_vs17_k6_metrics(summary)

    assert metrics == {
        "http_req_failed_rate": 0.0,
        "http_req_duration_p95_ms": 2.05,
        "http_reqs_count": 500.0,
    }


def test_extract_k6_metrics_supports_expected_response_duration_metric():
    summary = {
        "metrics": {
            "http_req_failed": {"value": 0.0},
            "http_req_duration{expected_response:true}": {"p(95)": 2.15},
            "http_reqs": {"count": 500},
        }
    }

    metrics = extract_vs17_k6_metrics(summary)

    assert metrics == {
        "http_req_failed_rate": 0.0,
        "http_req_duration_p95_ms": 2.15,
        "http_reqs_count": 500.0,
    }


def test_run_vs17_command_captures_exit_code():
    result = run_vs17_command(["python", "-c", "print('ok')"], timeout_seconds=2)
    assert result.exit_code == 0
    assert "ok" in result.stdout


def test_run_vs17_command_timeout_returns_124():
    result = run_vs17_command(
        ["python", "-c", "import time; time.sleep(2)"],
        timeout_seconds=1,
    )
    assert result.exit_code == 124


def test_build_evidence_payload_success_shape():
    profile = _fixture_profile()
    fixture_result = VS17FixturePumpResult(
        events_requested=3,
        events_published=3,
        publish_failures=0,
        first_correlation_id="c1",
        last_correlation_id="c3",
    )

    payload = build_vs17_evidence_payload(
        run_id="20260814T120000Z",
        profile=profile,
        k6_runner="host",
        k6_command=["k6", "run"],
        k6_result=None,
        k6_summary={
            "metrics": {
                "http_req_failed": {"values": {"rate": 0.0}},
                "http_req_duration": {"values": {"p(95)": 150.0}},
                "http_reqs": {"values": {"count": 20}},
            }
        },
        fixture_result=fixture_result,
        counters_before={
            "ingested_events": 10,
            "persisted_events": 10,
            "fanout_events": 10,
            "dropped_events": 0,
        },
        counters_after={
            "ingested_events": 13,
            "persisted_events": 13,
            "fanout_events": 12,
            "dropped_events": 1,
        },
        started_at=datetime(2026, 1, 1, tzinfo=UTC),
        finished_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert payload["status"] == "success"
    assert payload["evidence"] == {
        "ingest_events": 3,
        "persist_events": 3,
        "fanout_events": 2,
        "error_events": 1,
    }
    assert payload["acceptance_checks"]["fixture_publish_complete"] is True
    assert payload["acceptance_checks"]["k6_command_success"] is True


def test_build_evidence_payload_failed_when_reason_present():
    profile = _fixture_profile()
    fixture_result = VS17FixturePumpResult(
        events_requested=3,
        events_published=2,
        publish_failures=1,
        first_correlation_id="c1",
        last_correlation_id="c2",
    )

    payload = build_vs17_evidence_payload(
        run_id="20260814T120000Z",
        profile=profile,
        k6_runner="docker",
        k6_command=["docker", "run"],
        k6_result=None,
        k6_summary=None,
        fixture_result=fixture_result,
        counters_before={
            "ingested_events": 10,
            "persisted_events": 10,
            "fanout_events": 10,
            "dropped_events": 0,
        },
        counters_after={
            "ingested_events": 12,
            "persisted_events": 11,
            "fanout_events": 11,
            "dropped_events": 1,
        },
        started_at=datetime(2026, 1, 1, tzinfo=UTC),
        finished_at=datetime(2026, 1, 1, tzinfo=UTC),
        failure_reason="fixture_publish_incomplete",
    )

    assert payload["status"] == "failed"
    assert payload["failure_reason"] == "fixture_publish_incomplete"
    assert payload["acceptance_checks"]["fixture_publish_complete"] is False


def test_write_evidence_artifact_writes_json(tmp_path: Path):
    profile = _fixture_profile()
    payload = {"status": "success", "profile": {"name": profile.name}}

    artifact_path = write_vs17_evidence_artifact(
        evidence_payload=payload,
        output_dir=tmp_path,
        run_id="20260814T120000Z",
        profile=profile,
    )

    assert artifact_path.exists()
    content = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert content["status"] == "success"
    assert content["profile"]["name"] == "local-smoke"


def test_resolve_writable_output_dir_prefers_writable_path(tmp_path: Path):
    resolved = _resolve_writable_output_dir(output_dir=tmp_path, run_id="run123")
    assert resolved == tmp_path.resolve()


def test_resolve_writable_output_dir_falls_back_when_preferred_unwritable(tmp_path: Path):
    unwritable = tmp_path / "unwritable"
    with (
        patch(
            "scripts.run_vs17_external_load._is_writable_directory",
            side_effect=[False, True],
        ),
        patch("scripts.run_vs17_external_load.print") as mock_print,
    ):
        resolved = _resolve_writable_output_dir(output_dir=unwritable, run_id="run456")

    assert str(resolved).startswith("/tmp/opencode/vs17-artifacts-run456")
    mock_print.assert_called_once()


def test_resolve_writable_output_dir_raises_when_no_writable_paths(tmp_path: Path):
    with (
        patch(
            "scripts.run_vs17_external_load._is_writable_directory",
            side_effect=[False, False],
        ),
        pytest.raises(RuntimeError, match="Unable to resolve a writable output directory"),
    ):
        _resolve_writable_output_dir(output_dir=tmp_path / "blocked", run_id="run789")

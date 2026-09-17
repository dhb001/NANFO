"""Execute VS17 external load-tooling baseline and write evidence artifact."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.redis import close_redis, get_redis_client, init_redis
from app.modules.telemetry.counters import TelemetryHealthCounterService
from app.modules.telemetry.load_tooling import (
    VS17_DEFAULT_ARTIFACT_DIR,
    VS17_DEFAULT_K6_SCRIPT_PATH,
    VS17_LOAD_PROFILES,
    build_vs17_evidence_payload,
    build_vs17_k6_command,
    build_vs17_summary_path,
    get_vs17_load_profile,
    load_vs17_k6_summary,
    pump_vs17_synthetic_fixture,
    resolve_vs17_k6_runner,
    run_vs17_command,
    write_vs17_evidence_artifact,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run VS17 external load-tooling baseline")
    parser.add_argument(
        "--profile",
        choices=tuple(VS17_LOAD_PROFILES.keys()),
        default="local-smoke",
        help="Load profile to execute",
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("NANFO_BASE_URL", "http://127.0.0.1:8000"),
        help="Base URL for telemetry health endpoint load calls",
    )
    parser.add_argument(
        "--k6-mode",
        choices=("auto", "host", "docker"),
        default="auto",
        help="k6 runner mode",
    )
    parser.add_argument(
        "--auth-token",
        default=os.getenv("NANFO_AUTH_TOKEN"),
        help="Optional bearer token for authenticated telemetry health requests",
    )
    parser.add_argument(
        "--output-dir",
        default=str(VS17_DEFAULT_ARTIFACT_DIR),
        help="Output directory for VS17 evidence artifacts",
    )
    parser.add_argument(
        "--k6-script",
        default=str(VS17_DEFAULT_K6_SCRIPT_PATH),
        help="Path to VS17 k6 script",
    )
    parser.add_argument(
        "--k6-timeout-seconds",
        type=int,
        default=300,
        help="Timeout for k6 command execution",
    )
    parser.add_argument(
        "--skip-k6",
        action="store_true",
        help="Skip external k6 execution and run fixture/evidence only",
    )
    return parser


async def _run(args: argparse.Namespace) -> int:
    profile = get_vs17_load_profile(args.profile)
    output_dir = Path(args.output_dir)
    script_path = Path(args.k6_script)
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    started_at = datetime.now(UTC)

    k6_runner = "skipped"
    k6_command: list[str] = []
    k6_result = None
    k6_summary = None
    failure_reasons: list[str] = []

    script_path = script_path.resolve()
    output_dir = _resolve_writable_output_dir(output_dir=output_dir, run_id=run_id)

    await init_redis()
    try:
        redis = get_redis_client()
        counter_service = TelemetryHealthCounterService(redis)
        counters_before = await counter_service.get_snapshot()

        fixture_result = await pump_vs17_synthetic_fixture(redis=redis, profile=profile)
        if fixture_result.events_published != fixture_result.events_requested:
            failure_reasons.append("fixture_publish_incomplete")

        if not args.skip_k6:
            try:
                k6_runner = resolve_vs17_k6_runner(args.k6_mode)
            except RuntimeError as exc:
                failure_reasons.append("k6_runner_unavailable")
                k6_runner = "unavailable"
                k6_summary = None
                k6_result = None
                print(f"VS17 warning: {exc}")
            else:
                summary_path = build_vs17_summary_path(
                    output_dir=output_dir,
                    run_id=run_id,
                    profile=profile,
                )
                k6_command = build_vs17_k6_command(
                    runner=k6_runner,
                    profile=profile,
                    script_path=script_path,
                    summary_path=summary_path,
                    base_url=args.base_url,
                    auth_token=args.auth_token,
                )
                k6_result = run_vs17_command(k6_command, timeout_seconds=max(args.k6_timeout_seconds, 1))
                if k6_result.exit_code != 0:
                    failure_reasons.append(f"k6_exit_{k6_result.exit_code}")
                k6_summary = load_vs17_k6_summary(summary_path)

        counters_after = await counter_service.get_snapshot()

        finished_at = datetime.now(UTC)
        failure_reason = ",".join(failure_reasons) if failure_reasons else None
        evidence_payload = build_vs17_evidence_payload(
            run_id=run_id,
            profile=profile,
            k6_runner=k6_runner,
            k6_command=k6_command,
            k6_result=k6_result,
            k6_summary=k6_summary,
            fixture_result=fixture_result,
            counters_before=counters_before,
            counters_after=counters_after,
            started_at=started_at,
            finished_at=finished_at,
            failure_reason=failure_reason,
        )
        artifact_path = write_vs17_evidence_artifact(
            evidence_payload=evidence_payload,
            output_dir=output_dir,
            run_id=run_id,
            profile=profile,
        )

        counter_delta = evidence_payload["counters"]["delta"]
        print(f"VS17 artifact: {artifact_path}")
        print(f"VS17 status: {evidence_payload['status']}")
        print(
            "VS17 counters delta: "
            f"ingested={counter_delta['ingested_events']} "
            f"persisted={counter_delta['persisted_events']} "
            f"fanout={counter_delta['fanout_events']} "
            f"dropped={counter_delta['dropped_events']}"
        )

        return 0 if evidence_payload["status"] == "success" else 1
    finally:
        await close_redis()


def _resolve_writable_output_dir(*, output_dir: Path, run_id: str) -> Path:
    preferred = output_dir.resolve()
    if _is_writable_directory(preferred):
        return preferred

    fallback = Path("/tmp/opencode") / f"vs17-artifacts-{run_id}"
    if _is_writable_directory(fallback):
        print(
            "VS17 warning: preferred output directory is not writable; "
            f"falling back to {fallback}"
        )
        return fallback

    raise RuntimeError(
        "Unable to resolve a writable output directory for VS17 artifacts; "
        f"checked {preferred} and {fallback}"
    )


def _is_writable_directory(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())

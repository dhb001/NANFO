"""ADR023 operator-only bounded dry-run/apply/restore/reconcile CLI.

One-shot operations take ``--workspace-id`` and an explicit window. ``--loop``
(dry-run/apply only) is the supervised retention worker (ADR-028): every
``NANFO_TELEMETRY_RETENTION_INTERVAL_SECONDS`` it walks each coverage-enrolled
workspace (or ``--workspace-id``) from its oldest observation up to
``now - NANFO_TELEMETRY_RETENTION_MIN_AGE_DAYS`` (default 30) in bounded,
separately committed batches, and exits cleanly on SIGTERM/SIGINT.
"""

import argparse
import asyncio
import json
import os
import signal
import sys
import uuid
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.exc import SQLAlchemyError  # noqa: E402

from app.modules.telemetry.archive import TelemetryArchiveStore  # noqa: E402
from app.modules.telemetry.retention import ArchivalAssessmentRequest, TelemetryRetentionService  # noqa: E402
from app.modules.telemetry.retention_worker import TelemetryRetentionWorker  # noqa: E402

INTERVAL_ENV = "NANFO_TELEMETRY_RETENTION_INTERVAL_SECONDS"
MIN_AGE_ENV = "NANFO_TELEMETRY_RETENTION_MIN_AGE_DAYS"


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("operation", choices=["dry-run", "apply", "restore", "reconcile"])
    result.add_argument("--workspace-id", type=uuid.UUID)
    result.add_argument("--start-time")
    result.add_argument("--end-time")
    result.add_argument("--after", help="JSON next_position from a previous bounded sweep")
    result.add_argument("--batch-size", type=int, default=100)
    result.add_argument("--max-batches", type=int, default=10)
    result.add_argument("--timeout-seconds", type=int, default=30)
    result.add_argument("--archive-root")
    result.add_argument("--record-id", type=uuid.UUID)
    result.add_argument("--owner", choices=["report", "intent", "alert", "simulation", "autonomy"])
    result.add_argument("--loop", action="store_true",
                        help=f"supervised worker; interval from {INTERVAL_ENV}")
    result.add_argument("--min-age-days", type=float, default=None,
                        help=f"loop mode: only observations older than this (default {MIN_AGE_ENV} or 30)")
    return result


def loop_settings(args, environ=os.environ) -> tuple[float, timedelta]:
    raw_interval = environ.get(INTERVAL_ENV)
    if not raw_interval:
        raise ValueError(f"{INTERVAL_ENV} is required for --loop")
    interval = float(raw_interval)
    if not 1 <= interval <= 86400:
        raise ValueError(f"{INTERVAL_ENV} must be within 1..86400 seconds")
    days = args.min_age_days if args.min_age_days is not None else float(environ.get(MIN_AGE_ENV, "30"))
    if not 0 <= days <= 3650:
        raise ValueError("retention minimum age must be within 0..3650 days")
    return interval, timedelta(days=days)


async def run(args, *, stop: asyncio.Event | None = None):
    dsn = os.environ.get("TELEMETRY_RETENTION_DSN")
    if not dsn:
        raise ValueError("TELEMETRY_RETENTION_DSN is required")
    if args.loop and args.operation not in {"dry-run", "apply"}:
        raise ValueError("--loop supports dry-run and apply only")
    if not args.loop and args.workspace_id is None:
        raise ValueError("--workspace-id is required")
    if args.operation == "apply" and not args.archive_root:
        raise ValueError("apply requires --archive-root")
    interval, min_age = loop_settings(args) if args.loop else (None, None)
    engine = create_async_engine(dsn)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        worker = TelemetryRetentionWorker(sessions, settings={"max_batches": args.max_batches,
            "batch_timeout_seconds": args.timeout_seconds})
        if args.loop:
            if stop is None:
                stop = asyncio.Event()
                for name in (signal.SIGTERM, signal.SIGINT):
                    asyncio.get_running_loop().add_signal_handler(name, stop.set)
            if args.operation == "apply":
                TelemetryArchiveStore(args.archive_root)  # fail fast on an unsafe archive root
            await worker.run_forever(stop, interval_seconds=interval, apply=args.operation == "apply",
                                     archive_root=args.archive_root, min_age=min_age,
                                     workspace_ids=[args.workspace_id] if args.workspace_id else None)
            return {"stopped": True}
        if args.operation == "reconcile":
            if args.owner is None:
                raise ValueError("reconcile requires --owner")
            return await worker.reconcile(workspace_id=args.workspace_id, owner=args.owner, limit=args.batch_size)
        if args.operation == "restore":
            if args.record_id is None or args.archive_root is None:
                raise ValueError("restore requires --record-id and --archive-root")
            async with asyncio.timeout(args.timeout_seconds):
                async with sessions() as db:
                    restored = await TelemetryRetentionService(db).restore(workspace_id=args.workspace_id,
                        record_id=args.record_id, store=TelemetryArchiveStore(args.archive_root))
                    await db.commit()
                    return {"restored": restored, "record_id": str(args.record_id)}
        request = ArchivalAssessmentRequest(workspace_id=args.workspace_id, start_time=args.start_time,
                                            end_time=args.end_time, batch_size=args.batch_size,
                                            after=json.loads(args.after) if args.after else None)
        return await worker.sweep(request, apply=args.operation == "apply", archive_root=args.archive_root)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    try:
        print(json.dumps(asyncio.run(run(parser().parse_args())), sort_keys=True))
    except (ValueError, OSError, TimeoutError, SQLAlchemyError) as exc:
        print(json.dumps({"error": type(exc).__name__, "message": "Retention operation refused; verify scope, bounds, archive and coverage."}))
        sys.exit(1)

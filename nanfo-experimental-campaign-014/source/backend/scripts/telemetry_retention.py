"""ADR023 operator-only bounded dry-run/apply/restore/reconcile CLI."""

import argparse
import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.exc import SQLAlchemyError  # noqa: E402

from app.modules.telemetry.archive import TelemetryArchiveStore  # noqa: E402
from app.modules.telemetry.retention import ArchivalAssessmentRequest, TelemetryRetentionService  # noqa: E402
from app.modules.telemetry.retention_worker import TelemetryRetentionWorker  # noqa: E402


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("operation", choices=["dry-run", "apply", "restore", "reconcile"])
    result.add_argument("--workspace-id", required=True, type=uuid.UUID)
    result.add_argument("--start-time")
    result.add_argument("--end-time")
    result.add_argument("--after", help="JSON next_position from a previous bounded sweep")
    result.add_argument("--batch-size", type=int, default=100)
    result.add_argument("--max-batches", type=int, default=10)
    result.add_argument("--timeout-seconds", type=int, default=30)
    result.add_argument("--archive-root")
    result.add_argument("--record-id", type=uuid.UUID)
    result.add_argument("--owner", choices=["report", "intent", "alert", "simulation", "autonomy"])
    return result


async def run(args):
    dsn = os.environ.get("TELEMETRY_RETENTION_DSN")
    if not dsn:
        raise ValueError("TELEMETRY_RETENTION_DSN is required")
    engine = create_async_engine(dsn)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        worker = TelemetryRetentionWorker(sessions, settings={"max_batches": args.max_batches,
            "batch_timeout_seconds": args.timeout_seconds})
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
        if args.operation == "apply" and not args.archive_root:
            raise ValueError("apply requires --archive-root")
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

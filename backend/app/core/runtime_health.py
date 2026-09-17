"""ADR020 read-only dependency probes and work-coupled worker progress."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy import text

from app.core.config import get_settings

PROBE_TIMEOUT_SECONDS = 2.0
SCHEMA_HEAD = "0019"
WORKER_LOOPS = {
    "simulation": ("simulation", "outbox"),
    "report": ("report", "outbox"),
    "alert": ("outbox",),
    "execution": ("execution", "outbox"),
    "autonomy": ("cycles", "overrides"),
}


def process_start(pid: int) -> str:
    # Linux deployment PID namespaces reuse PID 1 on restart. A live PID alone
    # must not validate the previous process's heartbeat on a retained volume.
    return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]


async def dependency_checks(*, sessions, redis, neo4j=None) -> dict[str, str]:
    """Factories are resolved inside deadlines, including connection acquisition."""
    checks = {
        "postgres": "unavailable",
        "schema": "unavailable",
        "redis": "unavailable",
    }

    async def postgres_check():
        try:
            async with asyncio.timeout(PROBE_TIMEOUT_SECONDS), sessions() as db:
                if (await db.execute(text("SELECT 1"))).scalar_one() != 1:
                    return
                checks["postgres"] = "ok"
                revisions = (
                    (await db.execute(text("SELECT version_num FROM alembic_version")))
                    .scalars()
                    .all()
                )
                checks["schema"] = "ok" if revisions == [SCHEMA_HEAD] else "unavailable"
        except Exception:  # noqa: BLE001 - public diagnostics never contain exception text
            checks["schema"] = "unavailable"

    async def redis_check():
        try:
            async with asyncio.timeout(PROBE_TIMEOUT_SECONDS):
                if await redis().ping():
                    checks["redis"] = "ok"
        except Exception:  # noqa: BLE001
            checks["redis"] = "unavailable"

    async def neo4j_check():
        checks["neo4j"] = "unavailable"
        try:
            async with (
                asyncio.timeout(PROBE_TIMEOUT_SECONDS),
                neo4j().session() as session,
            ):
                result = await session.run("RETURN 1 AS ready")
                record = await result.single(strict=True)
                if record["ready"] == 1:
                    checks["neo4j"] = "ok"
        except Exception:  # noqa: BLE001
            checks["neo4j"] = "unavailable"

    await asyncio.gather(
        postgres_check(), redis_check(), *([neo4j_check()] if neo4j else [])
    )
    return checks


@asynccontextmanager
async def worker_iteration(loop: str):
    """Only completed bounded iterations (including empty polls) refresh progress."""
    settings = get_settings()
    async with asyncio.timeout(settings.WORKER_ITERATION_TIMEOUT_SECONDS):
        yield
    if not settings.WORKER_HEARTBEAT_PATH:
        return
    path = Path(f"{settings.WORKER_HEARTBEAT_PATH}.{loop}")
    # Atomic replacement prevents a simultaneous probe reading a partial record.
    fd, temporary = tempfile.mkstemp(prefix=".heartbeat-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="ascii") as output:
            json.dump(
                {
                    "pid": os.getpid(),
                    "start": process_start(os.getpid()),
                    "progress": time.monotonic(),
                },
                output,
            )
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def heartbeat_checks(worker: str) -> dict[str, str]:
    settings = get_settings()
    checks = {}
    for loop in WORKER_LOOPS[worker]:
        checks[loop] = "unavailable"
        if not settings.WORKER_HEARTBEAT_PATH:
            continue
        try:
            path = Path(f"{settings.WORKER_HEARTBEAT_PATH}.{loop}")
            with path.open(encoding="ascii") as source:
                record = json.loads(source.read(1024))
            pid = record["pid"]
            if type(pid) is not int or pid <= 0:
                continue
            age = time.monotonic() - record["progress"]
            if not 0 <= age <= settings.WORKER_HEARTBEAT_MAX_AGE_SECONDS:
                continue
            os.kill(pid, 0)
            if record["start"] != process_start(pid):
                continue
            checks[loop] = "ok"
        except (OSError, ValueError, KeyError, TypeError):
            pass
    return checks

"""Read-only dependency and genuine loop-progress health contracts."""

import asyncio
import json
import os
import sys
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core import runtime_health
from app.core.config import get_settings
from app.core.runtime_health import (
    dependency_checks,
    heartbeat_checks,
    worker_iteration,
)
from scripts import check_worker_health


@pytest.fixture
def infrastructure():
    db = AsyncMock()
    db.execute.side_effect = [
        MagicMock(scalar_one=lambda: 1),
        MagicMock(scalars=lambda: SimpleNamespace(all=lambda: ["0019"])),
    ]
    sessions = MagicMock(return_value=MagicMock(__aenter__=AsyncMock(return_value=db)))
    redis = SimpleNamespace(ping=AsyncMock(return_value=True))
    session = AsyncMock()
    session.run.return_value.single.return_value = {"ready": 1}
    driver = MagicMock()
    driver.session.return_value.__aenter__.return_value = session
    return sessions, redis, driver, db, session


async def test_dependencies_query_exact_head_and_execute_neo4j(infrastructure):
    sessions, redis, driver, db, session = infrastructure
    assert await dependency_checks(
        sessions=sessions, redis=lambda: redis, neo4j=lambda: driver
    ) == {
        "postgres": "ok",
        "schema": "ok",
        "redis": "ok",
        "neo4j": "ok",
    }
    assert [str(call.args[0]) for call in db.execute.await_args_list] == [
        "SELECT 1",
        "SELECT version_num FROM alembic_version",
    ]
    session.run.assert_awaited_once_with("RETURN 1 AS ready")
    session.run.return_value.single.assert_awaited_once_with(strict=True)


@pytest.mark.parametrize("dependency", ["postgres", "redis", "neo4j"])
async def test_dependency_down_is_named_without_secret(
    infrastructure, dependency, capsys
):
    sessions, redis, driver, db, session = infrastructure
    call = {"postgres": db.execute, "redis": redis.ping, "neo4j": session.run}[
        dependency
    ]
    call.side_effect = RuntimeError("postgres://private:secret@internal-host")
    checks = await dependency_checks(
        sessions=sessions, redis=lambda: redis, neo4j=lambda: driver
    )
    assert checks[dependency] == "unavailable"
    assert "secret" not in json.dumps(checks) + capsys.readouterr().out


@pytest.mark.parametrize("heads", [[], ["0018"], ["0019", "0020"]])
async def test_wrong_or_missing_schema_head_is_not_ready(infrastructure, heads):
    sessions, redis, _, db, _ = infrastructure
    db.execute.side_effect = [
        MagicMock(scalar_one=lambda: 1),
        MagicMock(scalars=lambda: SimpleNamespace(all=lambda: heads)),
    ]
    checks = await dependency_checks(sessions=sessions, redis=lambda: redis)
    assert checks == {"postgres": "ok", "schema": "unavailable", "redis": "ok"}


async def test_missing_schema_table_is_not_ready(infrastructure):
    sessions, redis, _, db, _ = infrastructure
    db.execute.side_effect = [
        MagicMock(scalar_one=lambda: 1),
        RuntimeError("missing alembic_version"),
    ]
    assert await dependency_checks(sessions=sessions, redis=lambda: redis) == {
        "postgres": "ok",
        "schema": "unavailable",
        "redis": "ok",
    }


async def test_all_connection_acquisitions_are_bounded_in_parallel(
    infrastructure, monkeypatch
):
    sessions, redis, driver, _, _ = infrastructure

    async def stall(*args, **kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr(runtime_health, "PROBE_TIMEOUT_SECONDS", 0.02)
    sessions.return_value.__aenter__.side_effect = stall
    redis.ping.side_effect = stall
    driver.session.return_value.__aenter__.side_effect = stall
    async with asyncio.timeout(0.5):
        checks = await dependency_checks(
            sessions=sessions, redis=lambda: redis, neo4j=lambda: driver
        )
    assert set(checks.values()) == {"unavailable"}


@pytest.fixture
def heartbeat_settings(monkeypatch, tmp_path):
    settings = get_settings().model_copy(
        update={
            "WORKER_HEARTBEAT_PATH": str(tmp_path / "progress"),
            "WORKER_HEARTBEAT_MAX_AGE_SECONDS": 0.1,
            "WORKER_ITERATION_TIMEOUT_SECONDS": 0.03,
        }
    )
    monkeypatch.setattr(runtime_health, "get_settings", lambda: settings)
    return settings


async def test_idle_poll_is_progress_but_other_live_loop_cannot_mask_stall(
    heartbeat_settings,
):
    assert set(heartbeat_checks("execution").values()) == {"unavailable"}
    async with worker_iteration("execution"):
        assert await AsyncMock(return_value=False)() is False
    async with worker_iteration("outbox"):
        pass
    assert set(heartbeat_checks("execution").values()) == {"ok"}
    await asyncio.sleep(0.12)
    async with worker_iteration("outbox"):
        pass
    assert heartbeat_checks("execution") == {"execution": "unavailable", "outbox": "ok"}


@pytest.mark.parametrize("failure", ["exception", "timeout", "cancel"])
async def test_failed_or_stalled_work_never_refreshes_progress(
    heartbeat_settings, failure
):
    with pytest.raises((ValueError, TimeoutError, asyncio.CancelledError)):
        async with worker_iteration("report"):
            if failure == "exception":
                raise ValueError("failed")
            if failure == "cancel":
                raise asyncio.CancelledError()
            await asyncio.Event().wait()
    assert heartbeat_checks("report")["report"] == "unavailable"


async def test_local_default_does_not_write_or_require_directory(
    heartbeat_settings, monkeypatch
):
    heartbeat_settings.WORKER_HEARTBEAT_PATH = ""
    write = MagicMock(side_effect=AssertionError("unexpected write"))
    monkeypatch.setattr(runtime_health.tempfile, "mkstemp", write)
    async with worker_iteration("report"):
        pass
    write.assert_not_called()
    assert set(heartbeat_checks("report").values()) == {"unavailable"}


@pytest.mark.parametrize(
    "record",
    [
        "invalid",
        {},
        {"pid": -1, "progress": 1},
        {"pid": os.getpid(), "progress": float("nan")},
        {"pid": os.getpid(), "progress": time.monotonic() + 1000},
    ],
)
def test_invalid_heartbeat_fails_closed(heartbeat_settings, record):
    path = runtime_health.Path(f"{heartbeat_settings.WORKER_HEARTBEAT_PATH}.outbox")
    path.write_text(json.dumps(record))
    assert heartbeat_checks("alert") == {"outbox": "unavailable"}


async def test_dead_process_heartbeat_fails_closed(heartbeat_settings, monkeypatch):
    async with worker_iteration("outbox"):
        pass
    monkeypatch.setattr(
        runtime_health.os, "kill", MagicMock(side_effect=ProcessLookupError)
    )
    assert heartbeat_checks("alert") == {"outbox": "unavailable"}


async def test_reused_pid_does_not_validate_previous_process(
    heartbeat_settings, monkeypatch
):
    async with worker_iteration("outbox"):
        pass
    monkeypatch.setattr(runtime_health, "process_start", lambda pid: "different-start")
    assert heartbeat_checks("alert") == {"outbox": "unavailable"}


def test_health_cli_sanitizes_config_failures(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["check_worker_health.py", "--worker", "report"])
    monkeypatch.setattr(
        check_worker_health,
        "check",
        AsyncMock(side_effect=ValueError("credential-sentinel")),
    )
    monkeypatch.setattr(check_worker_health.logging, "disable", MagicMock())
    assert check_worker_health.main() == 1
    output = capsys.readouterr()
    assert json.loads(output.out) == {
        "ready": False,
        "checks": {"runtime": "unavailable"},
    }
    assert "credential-sentinel" not in output.out + output.err


@pytest.mark.parametrize("worker_name", ["simulation", "report", "alert"])
async def test_script_once_heartbeats_only_completed_actual_calls(
    heartbeat_settings, monkeypatch, worker_name
):
    from importlib import import_module

    script = import_module(f"scripts.run_{worker_name}_worker")
    monkeypatch.setattr(sys, "argv", [script.__name__, "--once"])
    monkeypatch.setattr(script.Redis, "from_url", MagicMock(return_value=AsyncMock()))
    worker = AsyncMock()
    worker.run_one.return_value = False
    worker.publish_one.return_value = False
    if worker_name == "alert":
        monkeypatch.setattr(
            script, "AsyncSessionLocal", MagicMock(return_value=AsyncMock())
        )
        monkeypatch.setattr(script, "AlertRepository", MagicMock(return_value=worker))
    else:
        monkeypatch.setattr(
            script, f"{worker_name.title()}Worker", MagicMock(return_value=worker)
        )
    await script.main()
    assert set(heartbeat_checks(worker_name).values()) == {"ok"}
    worker.publish_one.assert_awaited_once()
    if worker_name != "alert":
        worker.run_one.assert_awaited_once()


@pytest.mark.parametrize("loop", ["execution", "outbox", "cycles", "overrides"])
@pytest.mark.parametrize("fails", [False, True])
async def test_independent_loops_heartbeat_only_successful_iteration(
    heartbeat_settings, monkeypatch, loop, fails
):
    from app.modules.autonomy.overrides import OverrideWorker
    from app.modules.autonomy.worker import AutonomyWorker
    from app.modules.intent.worker import ExecutionWorker

    owner, method, operation, worker_name = {
        "execution": (ExecutionWorker, "_execution_loop", "run_one", "execution"),
        "outbox": (ExecutionWorker, "_publish_loop", "publish_one", "execution"),
        "cycles": (AutonomyWorker, "_cycles", "run_one", "autonomy"),
        "overrides": (OverrideWorker, "run", "run_one", "autonomy"),
    }[loop]
    worker = object.__new__(owner)
    worker.settings = SimpleNamespace(EMULATION_EXECUTION_POLL_SECONDS=1)
    worker.owner = "test-worker"
    call = AsyncMock(
        return_value=False, side_effect=RuntimeError("failed") if fails else None
    )
    setattr(worker, operation, call)
    monkeypatch.setattr(asyncio, "sleep", AsyncMock(side_effect=asyncio.CancelledError))
    with pytest.raises(asyncio.CancelledError):
        await getattr(worker, method)()
    call.assert_awaited_once()
    assert heartbeat_checks(worker_name)[loop] == ("unavailable" if fails else "ok")


async def test_cli_checks_dependencies_and_heartbeat_without_work(
    heartbeat_settings, monkeypatch
):
    async with worker_iteration("outbox"):
        pass
    engine = SimpleNamespace(dispose=AsyncMock())
    redis = AsyncMock()
    monkeypatch.setattr(check_worker_health, "get_settings", lambda: heartbeat_settings)
    monkeypatch.setattr(
        check_worker_health, "create_async_engine", MagicMock(return_value=engine)
    )
    monkeypatch.setattr(
        check_worker_health.Redis, "from_url", MagicMock(return_value=redis)
    )
    probes = AsyncMock(
        return_value={"postgres": "ok", "schema": "ok", "redis": "unavailable"}
    )
    monkeypatch.setattr(check_worker_health, "dependency_checks", probes)
    result = await check_worker_health.check("alert")
    assert not result["ready"]
    assert result["checks"]["heartbeat_outbox"] == "ok"
    probes.assert_awaited_once()
    redis.aclose.assert_awaited_once()
    engine.dispose.assert_awaited_once()

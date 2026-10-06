"""In-process event-loop watchdog (ADR-028 deployment review).

Container healthchecks mark a hung process *unhealthy* but never restart it, so a
process whose event loop is stuck stayed unhealthy forever. The watchdog turns a
stalled loop into a process exit that the container restart policy acts on:

* a periodic asyncio task stamps a monotonic heartbeat every
  ``WATCHDOG_HEARTBEAT_INTERVAL_SECONDS``;
* a daemon thread checks the stamp every ``WATCHDOG_CHECK_INTERVAL_SECONDS``. When
  it is older than ``WATCHDOG_TIMEOUT_SECONDS`` the thread logs one structured
  critical event (``process_watchdog_timeout``: process, pid, stalled seconds and
  the stalled loop thread's frames as ``file:line:function`` — never values) and
  calls ``os._exit(70)`` (``EX_SOFTWARE``).

``os._exit`` is deliberate: a blocked loop cannot run shutdown handlers and normal
interpreter teardown could wait on the very thread that is stuck. The report runs
on a helper thread bounded by ``REPORT_TIMEOUT_SECONDS`` so a wedged log handler can
never prevent the exit. A whole-process freeze (``docker pause``, SIGSTOP, host
suspend) shows up as the watchdog thread itself oversleeping; it re-arms the timeout
instead of killing a process that was merely not scheduled. Cancelling the heartbeat
task (``stop()`` or loop teardown) disarms the watchdog, so shutdown is never
mistaken for a hang.

Enabled by default except for ``APP_ENV`` test/testing (``Settings.watchdog_enabled``).
The API installs it in ``app.runtime.lifespan``; worker runners use
:func:`watchdog_guard`. Clock, wait, exit and logger are injectable for tests.
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import sys
import threading
import time
import traceback
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Any

from app.core.logging import get_logger

EXIT_CODE = 70  # EX_SOFTWARE: internal software error; the restart policy restarts it.
REPORT_TIMEOUT_SECONDS = 2.0
_MAX_FRAMES = 20

logger = get_logger(__name__)


def _flush_output() -> None:
    """Best effort: ``os._exit`` skips buffered-stream flushing."""
    for handler in logging.getLogger().handlers:
        try:
            handler.flush()
        except Exception:  # noqa: BLE001 - the exit must not depend on log handlers
            pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except Exception:  # noqa: BLE001
            pass


class ProcessWatchdog:
    """Heartbeat written by the event loop, checked by a daemon thread."""

    def __init__(
        self,
        name: str,
        *,
        timeout_seconds: float,
        heartbeat_interval_seconds: float,
        check_interval_seconds: float,
        clock: Callable[[], float] = time.monotonic,
        exit_process: Callable[[int], Any] = os._exit,
        log: Any = None,
        wait: Callable[[float], bool] | None = None,
        report_timeout_seconds: float = REPORT_TIMEOUT_SECONDS,
    ):
        values = (timeout_seconds, heartbeat_interval_seconds, check_interval_seconds, report_timeout_seconds)
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in values):
            raise ValueError("Watchdog durations must be numbers")
        if any(not math.isfinite(value) or value <= 0 for value in values):
            raise ValueError("Watchdog durations must be finite and positive")
        if heartbeat_interval_seconds >= timeout_seconds or check_interval_seconds >= timeout_seconds:
            raise ValueError("Watchdog heartbeat and check intervals must be shorter than the timeout")
        self.name = name
        self.timeout_seconds = float(timeout_seconds)
        self.heartbeat_interval_seconds = float(heartbeat_interval_seconds)
        self.check_interval_seconds = float(check_interval_seconds)
        self._clock = clock
        self._exit = exit_process
        self._log = log if log is not None else logger
        self._stopped = threading.Event()
        self._wait = wait if wait is not None else self._stopped.wait
        self._report_timeout = float(report_timeout_seconds)
        self._last_beat = clock()
        self._rearmed_at = self._last_beat
        self._loop_thread_id: int | None = None
        self._task: asyncio.Task | None = None
        self._thread: threading.Thread | None = None
        self._fired = False

    # Loop side ---------------------------------------------------------------
    def beat(self) -> None:
        """Record liveness (a float store is atomic under the GIL)."""
        self._last_beat = self._clock()

    async def _heartbeat(self) -> None:
        while True:
            self.beat()
            await asyncio.sleep(self.heartbeat_interval_seconds)

    def _heartbeat_done(self, task: asyncio.Task) -> None:
        # stop(), loop teardown (even before the first beat) or a heartbeat bug:
        # disarm, so shutdown or a watchdog defect is never mistaken for a hang.
        self._stopped.set()
        if not task.cancelled() and task.exception() is not None:
            logger.error("process_watchdog_heartbeat_failed", process=self.name,
                         error_type=type(task.exception()).__name__)

    def start(self) -> ProcessWatchdog:
        """Arm from inside the running event loop that must stay responsive."""
        if self._thread is not None:
            raise RuntimeError("Watchdog already started")
        loop = asyncio.get_running_loop()
        self._loop_thread_id = threading.get_ident()
        self.beat()
        self._rearmed_at = self._last_beat
        self._task = loop.create_task(self._heartbeat(), name=f"watchdog-heartbeat:{self.name}")
        self._task.add_done_callback(self._heartbeat_done)
        self._thread = threading.Thread(target=self._watch, name=f"watchdog:{self.name}", daemon=True)
        self._thread.start()
        logger.info("process_watchdog_started", process=self.name, timeout_seconds=self.timeout_seconds,
                    heartbeat_interval_seconds=self.heartbeat_interval_seconds,
                    check_interval_seconds=self.check_interval_seconds)
        return self

    async def stop(self) -> None:
        """Disarm; idempotent. The daemon thread ends at its next wake-up."""
        self._stopped.set()
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    # Thread side -------------------------------------------------------------
    @property
    def fired(self) -> bool:
        return self._fired

    @property
    def stopped(self) -> bool:
        return self._stopped.is_set()

    def stale_seconds(self, now: float | None = None) -> float:
        now = self._clock() if now is None else now
        return now - max(self._last_beat, self._rearmed_at)

    def check(self, now: float | None = None) -> bool:
        """One thread-side evaluation; True once the process has been terminated."""
        if self._fired:
            return True
        if self._stopped.is_set():
            return False
        stale = self.stale_seconds(now)
        if stale <= self.timeout_seconds:
            return False
        self._fired = True
        self._terminate(stale)
        return True

    def _watch(self) -> None:
        previous = self._clock()
        while not self._wait(self.check_interval_seconds):
            now = self._clock()
            if now - previous > self.check_interval_seconds + self.timeout_seconds / 2:
                # This thread overslept as well: the whole process was frozen, which
                # is not a loop hang. Give the loop a full timeout to beat again.
                self._rearmed_at = now
                self._report("process_watchdog_rearmed", level="warning",
                             overslept_seconds=round(now - previous, 3))
            previous = now
            if self.check(now):
                return

    def _loop_frames(self) -> list[str]:
        """Innermost frames of the stalled loop thread (locations only, no values)."""
        frame = sys._current_frames().get(self._loop_thread_id) if self._loop_thread_id is not None else None
        if frame is None:
            return []
        summary = traceback.StackSummary.extract(
            traceback.walk_stack(frame), limit=_MAX_FRAMES, lookup_lines=False, capture_locals=False,
        )
        return [f"{item.filename}:{item.lineno}:{item.name}" for item in summary]

    def _report(self, event: str, *, level: str, **fields) -> None:
        try:
            getattr(self._log, level)(event, process=self.name, pid=os.getpid(), **fields)
        except Exception:  # noqa: BLE001 - reporting never changes the watchdog decision
            pass

    def _terminate(self, stale: float) -> None:
        try:
            frames = self._loop_frames()
        except Exception:  # noqa: BLE001 - diagnostics are optional; the exit is not
            frames = []
        reported = threading.Event()

        def report() -> None:
            try:
                self._report("process_watchdog_timeout", level="critical", stalled_seconds=round(stale, 3),
                             timeout_seconds=self.timeout_seconds, exit_code=EXIT_CODE,
                             loop_thread_frames=frames)
                _flush_output()
            finally:
                reported.set()

        # A log handler wedged by the same fault must not keep the process alive.
        threading.Thread(target=report, name=f"watchdog-report:{self.name}", daemon=True).start()
        reported.wait(self._report_timeout)
        self._exit(EXIT_CODE)


def build_watchdog(name: str, settings: Any = None, **overrides: Any) -> ProcessWatchdog | None:
    """Watchdog configured from settings, or None when disabled (tests by default)."""
    if settings is None:
        from app.core.config import get_settings

        settings = get_settings()
    # Strict identity check: a mocked settings object must never arm a real exit.
    if getattr(settings, "watchdog_enabled", False) is not True:
        return None
    return ProcessWatchdog(
        name,
        timeout_seconds=settings.WATCHDOG_TIMEOUT_SECONDS,
        heartbeat_interval_seconds=settings.WATCHDOG_HEARTBEAT_INTERVAL_SECONDS,
        check_interval_seconds=settings.WATCHDOG_CHECK_INTERVAL_SECONDS,
        **overrides,
    )


def start_watchdog(name: str, settings: Any = None, **overrides: Any) -> ProcessWatchdog | None:
    """Build and arm inside the running loop; None when disabled."""
    watchdog = build_watchdog(name, settings, **overrides)
    return watchdog.start() if watchdog is not None else None


@asynccontextmanager
async def watchdog_guard(name: str, settings: Any = None, **overrides: Any):
    """Arm for the body of a worker ``main``; always disarmed on exit."""
    watchdog = start_watchdog(name, settings, **overrides)
    try:
        yield watchdog
    finally:
        if watchdog is not None:
            await watchdog.stop()

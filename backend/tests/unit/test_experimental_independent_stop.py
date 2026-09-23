"""Durable reviewed STOP probes from campaign014 frozen_independent_review.py.

Preserves the two independently reviewed interleavings (original lines77–128).
No historical-plan, mutable workspace import, service startup or device I/O.
"""

import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest


async def test_stop_during_final_current_authority_read_is_not_admitted():
    from app.modules.autonomy.experimental.controller import ExperimentalController
    from tests.experimental_lab_support import case
    fixture = case()
    ctl = ExperimentalController(lambda: None, fixture.authority, None, fixture.policy)
    stopped = False
    calls = 0

    async def state(**kwargs):
        if stopped:
            raise ValueError("experimental_stop_latched")
        return datetime.now(UTC) + timedelta(seconds=30)

    async def authority(policy):
        nonlocal calls, stopped
        calls += 1
        if calls == 2:
            stopped = True

    ctl._checkpoint_state = state
    ctl.authority = SimpleNamespace(check=authority)
    with pytest.raises(ValueError, match="stop"):
        await ctl.checkpoint()


def test_bootstrap_stop_during_admission_read_is_not_admitted(tmp_path, monkeypatch):
    import emulation.experimental_lab_receiver as module
    from emulation.tests.test_experimental_lab import ContractTests
    from emulation.experimental_lab_contract import atomic_write, Request, canonical
    tmp_path.chmod(0o700)
    receiver, *_ = ContractTests().receiver(tmp_path)
    req = ContractTests().wire(receiver, "bootstrap")
    receiver.current = Request.parse(canonical(req))
    atomic_write(tmp_path / "bootstrap-admission.json", {
        "policy_sha256": receiver.policy_hash, "request_id": req["request_id"],
        "expires_at": time.time() + 30, "authorized": True})
    original = module.protected_read

    def reading(path, *args):
        raw = original(path, *args)
        if Path(path).name == "bootstrap-admission.json":
            receiver.latch_stop("independent-test", "stop-1")
        return raw

    monkeypatch.setattr(module, "protected_read", reading)
    try:
        with pytest.raises(ValueError, match="stop|authority"):
            receiver.authority()
    finally:
        os.close(receiver.claim)

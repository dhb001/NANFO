"""Finding8: every blocking preflight read precedes final mutation authority."""

import pytest
from unittest.mock import AsyncMock

from emulation.autonomous_receiver import AutonomousReceiver
from tests.autonomous_execution_support import fixture
from tests.unit.test_autonomous_execution import Journal
from tests.unit.test_autonomous_frr import driver, plan


@pytest.mark.parametrize("failure", ["actor_revoked", "certificate_expired"])
@pytest.mark.parametrize("read_number", range(1, 23))
async def test_any_final_inventory_read_invalidates_first_add(failure, read_number):
    device = driver()
    prepared = await device.prepare(plan())
    original = device.network.command
    reads, allowed, now = 0, True, 0
    def command(node, args, timeout=5):
        nonlocal reads, allowed, now
        if args[:2] == ["ip", "-j"]:
            reads += 1
            if reads == read_number:
                allowed, now = False, 10
        return original(node, args, timeout)
    device.network.command = command
    async def checkpoint():
        if (failure == "actor_revoked" and not allowed) or (failure == "certificate_expired" and now >= 10):
            raise ValueError(failure)
    with pytest.raises(ValueError, match=failure):
        await device.apply(prepared, checkpoint)
    assert reads == 22
    assert device.network.writes == []  # Includes no implicit cleanup writes.


@pytest.mark.parametrize("mutation", range(12))
@pytest.mark.parametrize("operation", ["apply", "compensate"])
async def test_every_add_and_delete_has_no_inventory_between_checkpoint_and_write(operation, mutation):
    device = driver()
    prepared = await device.prepare(plan())
    if operation == "compensate":
        await device.apply(prepared, AsyncMock())
    original = device.network.command
    events, checks = [], 0
    writes_before = len(device.network.writes)
    def command(node, args, timeout=5):
        if args[:2] == ["ip", "-j"]:
            events.append("read")
        else:
            assert events[-1] == "checkpoint"
            events.append("write")
        return original(node, args, timeout)
    device.network.command = command
    async def checkpoint():
        nonlocal checks
        if checks == mutation:
            raise ValueError("final_authority_lost")
        checks += 1
        events.append("checkpoint")
    with pytest.raises(ValueError, match="final_authority_lost"):
        await getattr(device, operation)(prepared, checkpoint)
    assert len(device.network.writes) - writes_before == mutation
    assert checks == mutation  # Every preceding write had exactly one fresh check.


@pytest.mark.parametrize("read_number", range(1, 43))
async def test_restore_rechecks_independent_recovery_after_each_preflight_read(read_number):
    device = driver()
    prepared = await device.prepare(plan())
    await device.apply(prepared, AsyncMock())
    original = device.network.command
    reads, recovery_owned = 0, True
    def command(node, args, timeout=5):
        nonlocal reads, recovery_owned
        if args[:2] == ["ip", "-j"]:
            reads += 1
            if reads == read_number:
                recovery_owned = False
        return original(node, args, timeout)
    device.network.command = command
    async def recovery_checkpoint():
        if not recovery_owned:
            raise ValueError("recovery_fence_or_lease_lost")
    with pytest.raises(ValueError, match="recovery_fence_or_lease_lost"):
        await device.compensate(prepared, recovery_checkpoint)
    assert reads == 42  # Initial full sweep plus the last22 reads for first delete.
    assert len(device.network.writes) == 12  # No deletes after losing recovery authority.


@pytest.mark.parametrize("operation", ["apply", "compensate"])
async def test_blocking_final_namespace_binding_check_precedes_authority(operation):
    device = driver()
    prepared = await device.prepare(plan())
    if operation == "compensate":
        await device.apply(prepared, AsyncMock())
    original = device.network.command
    reads, authority = 0, True
    def command(node, args, timeout=5):
        nonlocal reads
        if args[:2] == ["ip", "-j"]:
            reads += 1
        return original(node, args, timeout)
    device.network.command = command
    def owned(*_):
        nonlocal authority
        if reads == (22 if operation == "apply" else 42):
            authority = False
        return True  # Namespace remains ours; separate server authority was revoked.
    device.ownership_check = owned
    async def checkpoint():
        if not authority:
            raise ValueError("authority_changed_during_binding_read")
    before = len(device.network.writes)
    with pytest.raises(ValueError, match="authority_changed_during_binding_read"):
        await getattr(device, operation)(prepared, checkpoint)
    assert len(device.network.writes) == before


async def test_revocation_during_prepare_is_read_only_and_prevents_apply():
    device, journal = driver(), Journal()
    command = fixture(runtime="frr").command
    original = device.network.command
    def read_then_revoke(node, args, timeout=5):
        assert args[:2] == ["ip", "-j"]
        journal.allowed = False
        return original(node, args, timeout)
    device.network.command = read_then_revoke
    result = await AutonomousReceiver(device).receive(command, journal)
    assert result["phase"] == "cancelled" and result["released"]
    assert device.network.writes == []


async def test_partial_apply_revocation_cleanup_requires_separate_recovery_boundary():
    device, journal = driver(), Journal()
    command = fixture(runtime="frr").command
    original = device.network.command
    recovered_checks = 0
    def command_io(node, args, timeout=5):
        if args[:2] == ["ip", "-j"] and device.network.writes:
            journal.allowed = False
        if args[1:3] in (["route", "del"], ["rule", "del"]):
            assert journal.record["phase"] == "recovering" and recovered_checks > 0
        return original(node, args, timeout)
    device.network.command = command_io
    recovery = journal.recovery_checkpoint
    async def recovery_checkpoint(value):
        nonlocal recovered_checks
        await recovery(value)
        recovered_checks += 1
    journal.recovery_checkpoint = recovery_checkpoint
    result = await AutonomousReceiver(device).receive(command, journal)
    assert not journal.allowed
    assert result["phase"] == "cancelled" and result["released"]
    assert [args[2] for _, args in device.network.writes] == ["add", "del"]
    assert recovered_checks == 1


async def test_denied_recovery_retains_uncertainty_without_cleanup_writes():
    device, journal = driver(), Journal()
    command = fixture(runtime="frr").command
    original = device.network.command
    def command_io(node, args, timeout=5):
        if args[:2] == ["ip", "-j"] and device.network.writes:
            journal.allowed = False
        return original(node, args, timeout)
    device.network.command = command_io
    journal.recovery_checkpoint = AsyncMock(side_effect=ValueError("recovery_fence_lost"))
    result = await AutonomousReceiver(device).receive(command, journal)
    assert result["phase"] == "uncertain" and not result["released"]
    assert [args[2] for _, args in device.network.writes] == ["add"]
    journal.recovery_checkpoint.assert_awaited_once()


async def test_prepare_and_verify_never_write_configuration():
    device = driver()
    prepared = await device.prepare(plan())
    assert device.network.writes == []
    await device.apply(prepared, AsyncMock())
    before = list(device.network.writes)
    await device.verify(prepared, plan())
    assert device.network.writes == before

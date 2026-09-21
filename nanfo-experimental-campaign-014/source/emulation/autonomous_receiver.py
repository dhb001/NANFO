"""ADR023 receiver state machine. No manual command parsing or approval synthesis.

The journal adapter owns PostgreSQL transactions/authority; the device interface
is injectable for unit tests and implemented by autonomous_driver for isolated OVS.
Every mutation is preceded by an authority/ownership checkpoint. The caller holds
a session-level resource lock for this entire invocation, including device I/O.
"""

from typing import Protocol


class AutonomousDevice(Protocol):
    async def prepare(self, plan: dict) -> dict: ...
    async def apply(self, prepared: dict, checkpoint) -> None: ...
    async def verify(self, prepared: dict, plan: dict) -> dict: ...
    async def compensate(self, prepared: dict, checkpoint) -> dict: ...


class AutonomousReceiver:
    def __init__(self, device: AutonomousDevice):
        self.device = device

    async def receive(self, command, journal):
        record = await journal.inspect(command)
        if record["released"]:
            return record["result"]
        recovery = command.operation == "recover" or record["cancel_requested"] or record["phase"] in {
            "applying", "recovering", "uncertain"}
        if not recovery:
            try:
                await journal.checkpoint(command, mutation=False)
            except Exception:  # authority denial also requires exact owned compensation
                recovery = True
        if record["phase"] == "verified" and not recovery:
            # Re-read actual device state; a previous success is not current readback.
            try:
                evidence = await self.device.verify(record["prepared"], command.plan.model_dump(mode="json"))
                return await journal.verified(command, evidence)
            except Exception:
                recovery = True
        if recovery:
            return await self.recover(command, journal, record)
        try:
            prepared = record["prepared"]
            if prepared is None:
                prepared = await self.device.prepare(command.plan.model_dump(mode="json"))
                await journal.prepare(command, prepared)
            # Commit dispatch possibility before the first device write.
            await journal.begin_apply(command)
            await self.device.apply(prepared, lambda: journal.checkpoint(command, mutation=True))
            evidence = await self.device.verify(prepared, command.plan.model_dump(mode="json"))
            await journal.checkpoint(command, mutation=False)
            return await journal.verified(command, evidence)
        except Exception:
            # Never re-execute an action after possible partial mutation or lost result.
            record = await journal.inspect(command)
            return await self.recover(command, journal, record)

    async def recover(self, command, journal, record):
        if record["phase"] in {"accepted", "prepared"}:
            return await journal.cancelled(command, {"not_dispatched": True})
        if record["prepared"] is None:
            return await journal.uncertain(command)
        try:
            await journal.begin_recovery(command)
            evidence = await self.device.compensate(record["prepared"], lambda: journal.recovery_checkpoint(command))
            return await journal.cancelled(command, evidence)
        except Exception:
            return await journal.uncertain(command)

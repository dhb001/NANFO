"""Public async adapter protocol; driver must checkpoint under its resource lock."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from .schemas import (
    ActionCommand, BootstrapCommand, BootstrapRecoveryReceipt, ExecutionReceipt, ExperimentalPolicy, InferenceRecord, MeasuredFrame,
    PreparedAction, RecoveryReceipt, SimulationRecord, VerificationRecord,
)

Checkpoint = Callable[[], Awaitable[None]]


class Observer(Protocol):
    async def observe(self) -> MeasuredFrame: ...


class Model(Protocol):
    async def infer(self, frame: MeasuredFrame) -> InferenceRecord: ...


class Simulator(Protocol):
    async def simulate(self, frame: MeasuredFrame, inference: InferenceRecord,
                       policy: ExperimentalPolicy) -> SimulationRecord: ...


class Transport(Protocol):
    async def prepare(self, command: ActionCommand) -> PreparedAction: ...
    async def execute(self, action: PreparedAction, checkpoint: Checkpoint) -> ExecutionReceipt: ...
    async def verify(self, action: PreparedAction) -> VerificationRecord: ...
    async def recover(self, action: PreparedAction, checkpoint: Checkpoint) -> RecoveryReceipt: ...
    # Required only when campaign explicitly admits bootstrap ownership.
    async def recover_bootstrap(self, command: BootstrapCommand, checkpoint: Checkpoint) -> BootstrapRecoveryReceipt: ...


@dataclass(frozen=True)
class Ports:
    observer: Observer
    model: Model
    simulator: Simulator
    transport: Transport

    def bind_checkpoint(self, checkpoint: Checkpoint):
        """Optional local wiring only, after controller construction, before I/O.

        An IPC adapter may need current authority during observation/verification
        heartbeats too. This setter must not perform I/O or mutate lab state.
        """
        seen = set()
        for adapter in (self.observer, self.transport):
            if id(adapter) not in seen:
                seen.add(id(adapter))
                setter = getattr(type(adapter), "bind_checkpoint", None)
                if setter is not None:
                    setter(adapter, checkpoint)

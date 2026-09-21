"""Independent bounded worker; no simulation computation in HTTP/event consumers."""

import asyncio

from app.modules.simulation.evaluator import advance, canonical_config, digest, output
from app.modules.simulation.repository import SimulationRepository
from app.modules.simulation.schemas import ScenarioConfig


class SimulationWorker:
    def __init__(self, *, sessions, redis, batch_ticks: int = 8):
        if type(batch_ticks) is not int or not 1 <= batch_ticks <= 32:
            raise ValueError("batch_ticks must be 1..32")
        self.sessions, self.redis, self.batch_ticks = sessions, redis, batch_ticks

    async def run_one(self) -> bool:
        async with self.sessions() as db:
            claimed = await SimulationRepository(db).claim()
        if claimed is None:
            return False
        try:
            config = ScenarioConfig.model_validate(claimed.scenario_config)
            if digest(canonical_config(config)) != claimed.input_sha256:
                raise ValueError("Input hash mismatch")
            checkpoint = await asyncio.to_thread(
                advance, config, claimed.checkpoint, ticks=self.batch_ticks
            )
            result = output(config, checkpoint)
        except (ValueError, TypeError, KeyError):
            async with self.sessions() as db:
                await SimulationRepository(db).finish_batch(
                    claimed,
                    checkpoint=None,
                    run_output=None,
                    failure="model_checkpoint_invalid",
                )
            return True
        async with self.sessions() as db:
            await SimulationRepository(db).finish_batch(
                claimed, checkpoint=checkpoint, run_output=result
            )
        return True

    async def publish_one(self) -> bool:
        async with self.sessions() as db:
            return await SimulationRepository(db).publish_one(self.redis)

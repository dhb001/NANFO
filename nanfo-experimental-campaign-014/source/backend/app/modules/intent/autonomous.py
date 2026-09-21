"""Public autonomous acceptance boundary; distinct from manual Intent execution.

ADR023 Autonomy owns the durable job. This interface intentionally does not write
manual intent approvals or call IntentExecutionService.execute_intent.
"""

from app.modules.autonomy.schemas import ExecutionAuthorization


class AutonomousAcceptance:
    def __init__(self, executor):
        self.executor = executor

    async def accept(self, db, authorization: ExecutionAuthorization):
        await self.executor.accept(db, ExecutionAuthorization.model_validate(authorization))

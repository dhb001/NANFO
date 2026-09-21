"""Read-only passive observation; never invokes reset, step, probes or collectors."""

import asyncio
from datetime import UTC, datetime

from app.modules.autonomy.artifact_io import EvidenceError
from app.modules.autonomy.live_schemas import OBSERVATION_CONTRACT
from app.modules.autonomy.schemas import Observation, ProviderStatus


class LiveObserver:
    status = ProviderStatus(provider_id="passive_measured_v4", status="ready")

    def __init__(self, registry):
        self.registry = registry

    async def observe(self, network_id, workspace_id):
        def read():
            installation = self.registry.load()
            snapshot, digest = self.registry.snapshot(installation, network_id, workspace_id)
            return installation, snapshot, digest

        try:
            installation, snapshot, digest = await asyncio.to_thread(read)
            now = datetime.now(UTC)
            return Observation(network_id=network_id, workspace_id=workspace_id,
                provider_id=self.status.provider_id, contract=OBSERVATION_CONTRACT,
                observed_at=snapshot.observed_at, collected_at=now,
                age_seconds=(now - snapshot.observed_at).total_seconds(), fresh=True, compatible=True,
                evidence=[f"passive_snapshot:{digest}", f"live_registry:{installation.sha256}",
                          f"measured_history:{snapshot.history_sha256}", f"run:{snapshot.run_id}",
                          "source:operator-attested-measured-lab"])
        except (ValueError, OSError) as exc:
            reason = str(exc) if isinstance(exc, EvidenceError) else "live_observation_invalid"
            return Observation(network_id=network_id, workspace_id=workspace_id,
                provider_id=self.status.provider_id, contract=OBSERVATION_CONTRACT,
                observed_at=None, collected_at=datetime.now(UTC), age_seconds=None,
                fresh=False, compatible=False, reasons=[reason])

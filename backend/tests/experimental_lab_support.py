"""Deterministic synthetic contract fixtures; never live lab evidence."""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from app.modules.autonomy.experimental.ports import Ports
from app.modules.autonomy.experimental.schemas import (
    ExecutionReceipt, ExperimentalPolicy, InferenceRecord, MeasuredFrame, PreparedAction,
    RecoveryReceipt, SimulationRecord, VerificationRecord, contract_digest, utcnow,
)
from app.modules.autonomy.live_schemas import MeasuredFeatures, PassiveSnapshot, RuntimeResult
from app.modules.autonomy.schemas import Observation, Proposal, Qualification

H = "a" * 64


def case():
    now = utcnow()
    policy = ExperimentalPolicy(version="nanfo.experimental-lab/v1", run_id=uuid4(), actor_id="test-actor",
        network_id=uuid4(), workspace_id=uuid4(), runtime=dict(resource_id="test-lab", container_id="test-container",
        image_sha256=H, source_sha256=H, wrapper_sha256=H, disposable=True, network_disconnected=True),
        registry_sha256=H, checkpoint_sha256=H, weights_sha256=H, model_source_sha256=H,
        preregistration_sha256=H, evaluator_sha256=H,
        routes=[dict(action_id="route0", device_ids=["router"], path=["src", "r0", "dst"])],
        assumptions={"queue": "configured"}, objectives={"goodput": "increase"},
        verification=dict(min_goodput_mbps=1, max_loss_fraction=.1, max_rtt_ms=100,
                          min_probe_sent=2, min_traffic_bytes=1),
        max_observation_age_seconds=30, min_dwell_seconds=0, max_actions=1,
        action_window_seconds=60, max_actions_per_window=1, max_action_duration_seconds=1.,
        lease_seconds=10, io_timeout_seconds=5, poll_seconds=2.,
        starts_at=now - timedelta(seconds=1), expires_at=now + timedelta(minutes=10))
    features = MeasuredFeatures(path_capacity_mbps=[10., 10.], path_utilization=[.8, .1],
        path_queue_packets=[2., 0.], latency_ms=10., loss_fraction=0., goodput_mbps=5., offered_mbps=6.,
        actual_offered_mbps=6., background_mbps=1., previous_action=1, seconds_since_change=10.)
    history = {"frames": [{"response": {"data": {"episode_id": str(policy.run_id),
        "observation": features.model_dump(mode="json")}}}]}
    snapshot = PassiveSnapshot(version="nanfo.passive-measured-v4.v1", network_id=policy.network_id,
        workspace_id=policy.workspace_id, snapshot_id=uuid4(), run_id=policy.run_id,
        observed_at=now, window_started_at=now - timedelta(seconds=3), published_at=now,
        source="operator-attested-measured-lab", contract_sha256=H, spec_sha256=H,
        history=history, history_sha256=contract_digest(history))
    observation = Observation(network_id=policy.network_id, workspace_id=policy.workspace_id,
        provider_id="fixture", contract=snapshot.version, observed_at=now, collected_at=now,
        age_seconds=0., fresh=True, compatible=True, evidence=["synthetic-test-only"])
    frame = MeasuredFrame(snapshot=snapshot, features=features, observation=observation,
        runtime=policy.runtime, provenance={"source": "synthetic-test-only"})
    result = RuntimeResult(operation="infer", registry_sha256=H, checkpoint_sha256=H, weights_sha256=H,
        source_sha256=H, contract_sha256=H, spec_sha256=H, report_sha256=H,
        scope="stationary-campus-small-v4-scoped-benchmark", snapshot_sha256=contract_digest(snapshot),
        history_sha256=snapshot.history_sha256, input_sha256=contract_digest(features),
        action=0, action_path=["src", "r0", "dst"], probabilities=[.9, .1], value=1., inference_seconds=.1)
    inference = InferenceRecord(frame_sha256=contract_digest(frame), result=result,
        proposal=Proposal(action_id="route0", checkpoint_sha256=H, observation_contract=snapshot.version,
                          evidence=["synthetic-test-only"]),
        qualification=Qualification(qualified=True, checkpoint_sha256=H, manifest_sha256=H,
                                    observation_contract=snapshot.version))
    simulation = SimulationRecord(frame_sha256=contract_digest(frame), inference_sha256=contract_digest(inference),
        policy_sha256=contract_digest(policy), action_id="route0", admitted=True, assumptions=policy.assumptions,
        objectives=policy.objectives, reasons=(), evaluator_sha256=H, result={"numeric": 1.})
    transport = FakeTransport()
    ports = Ports(AsyncMock(observe=AsyncMock(return_value=frame)),
        AsyncMock(infer=AsyncMock(return_value=inference)),
        AsyncMock(simulate=AsyncMock(return_value=simulation)), transport)
    return SimpleNamespace(policy=policy, frame=frame, inference=inference, simulation=simulation,
                           transport=transport, ports=ports, authority=AsyncMock())


class FakeTransport:
    def __init__(self):
        self.executes = self.recoveries = 0
        self.before_execute = self.before_recover = None
        self.ambiguous = False
        self.recovery_uncertain = False

    async def prepare(self, command):
        baseline = {"route": "original"}
        return PreparedAction(command=command, baseline=baseline,
                              baseline_sha256=contract_digest(baseline), ownership_sha256=H)

    async def execute(self, action, checkpoint):
        if self.before_execute:
            await self.before_execute(action)
        await checkpoint()
        self.executes += 1
        if self.ambiguous:
            raise TimeoutError("synthetic lost reply")
        return ExecutionReceipt(request_id=action.command.request_id, action_sha256=contract_digest(action),
            action_id=action.command.route.action_id, status="applied", evidence={"synthetic": True})

    async def verify(self, action):
        return VerificationRecord(request_id=action.command.request_id, action_sha256=contract_digest(action),
            run_id=action.command.run_id, action_id=action.command.route.action_id, route_verified=True,
            observed_at=utcnow(), window_started_at=action.command.created_at,
            goodput_mbps=5., loss_fraction=0., rtt_ms=10., probe_sent=2, probe_received=2,
            traffic_bytes=1000, provenance={"source": "synthetic-test-only"})

    async def recover(self, action, checkpoint):
        if self.before_recover:
            await self.before_recover(action)
        await checkpoint()
        self.recoveries += 1
        return RecoveryReceipt(request_id=action.command.request_id, action_sha256=contract_digest(action),
            baseline_sha256=action.baseline_sha256,
            status="uncertain" if self.recovery_uncertain else "restored", evidence={"synthetic": True})


def factory(*, policy, options):
    return case().ports

"""Synthetic provider/device fixtures; never installation/calibration evidence."""

import copy
import hashlib
import json
import uuid
from types import SimpleNamespace

from app.modules.autonomy.execution_contract import AutonomousCommand
from app.modules.autonomy.safety_provider import CalibratedSafetyProvider, ValidatedInstallation
from app.modules.autonomy.schemas import ExecutionAuthorization, canonical_json, contract_digest
from tests.autonomy_support import control_record, qualified_providers


def reviewed_config(data):
    from app.modules.autonomy.calibration_verification_models import NetworkQualificationConfig
    return NetworkQualificationConfig(schema_version="nanfo.network-qualification-config.v1",
        provider_id=data.calibration.provider_id, egress_ids=data.calibration.egress_ids,
        demand_ids=data.calibration.demand_ids, actions=[dict(action_id=a.action_id,
            demand_egress_ids={r.demand_id: next(p.egress_ids for p in data.policy.allowed_paths if p.route_id == r.route_id)
                              for r in a.routes}, bounds=[q.model_dump() for q in a.queues]) for a in data.actions],
        queue_units="bytes", rate_units="bytes/second", time_units="unix-seconds", dt_seconds=data.dt_seconds,
        max_delay_seconds=data.policy.max_delay_seconds, queue_threshold_bytes=data.policy.queue_threshold_bytes,
        drift_budget_bytes_squared=data.policy.drift_budget_bytes_squared, min_samples_per_action_per_split=2,
        required_transitions=data.transitions, execution=data.execution)


def fixture(*, runtime="ovs", horizon_seconds=1.):
    control = control_record()
    providers = qualified_providers(control)
    observation = providers.observer.observe.return_value
    proposal = providers.model.infer.return_value
    binding = providers.safety.assess.return_value.binding
    plan = {"operation": "reroute", "source_host": "h1", "destination_host": "h3",
            "paths": [["s1", "s3", "s2"]], "weights": [1], "rate_mbps": None, "dscp": None}
    data = dict(version="nanfo.calibrated-safety/v1", runtime_action="isolated-ovs-autonomous/v1",
        workspace_id=str(control.workspace_id),
        network_id=str(control.network_id), observation_contract=observation.contract, configuration_sha256="c" * 64,
        checkpoints=[proposal.checkpoint_sha256], policy=binding.policy.model_dump(mode="json"),
        calibration=binding.calibration.model_dump(mode="json"), dt_seconds=1.0, actuation_delay_upper_seconds=0.1,
        actions=[dict(action_id=proposal.action_id, routes=[{"demand_id": "demand-1", "route_id": "route-B"}],
            queues=[dict(egress_id=key, service_lower_bytes_per_second=20.0,
                service_upper_bytes_per_second=25.0, error_upper_bytes=1.0,
                arrival_upper_bytes_per_second=0.0 if key == "a" else 10.0,
                capacity_bytes_per_second=100.0) for key in ("a", "b")], plan=plan)],
        transitions=[("baseline", proposal.action_id)],
        evidence=[dict(path="synthetic.json", sha256="a" * 64, size_bytes=1)])
    baseline = copy.deepcopy(data["actions"][0])
    baseline["action_id"] = "baseline"
    baseline["routes"][0]["route_id"] = "route-A"
    baseline["queues"][0]["arrival_upper_bytes_per_second"] = 10.0
    baseline["queues"][1]["arrival_upper_bytes_per_second"] = 0.0
    data["actions"].append(baseline)
    if runtime == "frr":
        data["runtime_action"] = "isolated-linux-frr-host-route/v1"
        data["runtime_binding"] = {"path": "unit-runtime.json", "sha256": "b" * 64, "size_bytes": 1}
        for action, number in zip(data["actions"], (1, 0)):
            action["plan"] = {"runtime": data["runtime_action"], "action": number, "runtime_binding_sha256": "b" * 64}
        plan = data["actions"][0]["plan"]
    data["dt_seconds"] = horizon_seconds
    data["policy"]["max_dt_seconds"] = max(data["policy"]["max_dt_seconds"], horizon_seconds)
    data["policy"]["max_observation_age_seconds"] = max(data["policy"]["max_observation_age_seconds"], horizon_seconds)
    data["policy"]["max_delay_seconds"] = horizon_seconds - .1
    data["execution"] = dict(version="nanfo.reviewed-execution/v1", runtime=data["runtime_action"],
        plans={a["action_id"]: {k: v for k, v in a["plan"].items() if k != "runtime_binding_sha256"} for a in data["actions"]},
        egresses={key: dict(node="s", interface="port-" + key, queue_handle="10:", source="s", destination="t") for key in ("a", "b")},
        demands={"demand-1": dict(source="s", destination="t", source_node="h1", destination_node="h3",
                                   source_address="10.0.0.1", destination_address="10.0.0.3")})
    content = json.dumps(data).encode()
    installation = ValidatedInstallation(content, hashlib.sha256(content).hexdigest())
    installation = ValidatedInstallation(content, installation.sha256, reviewed_config(installation.data).model_dump_json().encode())
    provider = CalibratedSafetyProvider(None, installation)
    safety = provider.evaluate(observation, proposal, binding.observation, binding.state,
                               now=observation.observed_at.timestamp())
    assert safety.admissible
    auth = ExecutionAuthorization(decision_id=uuid.uuid4(), execution_id=uuid.uuid4(), intent_id=uuid.uuid4(),
        network_id=control.network_id, workspace_id=control.workspace_id, actor_id=control.approved_by_user_id,
        checkpoint_sha256=control.checkpoint_sha256, approval_expires_at=control.approval_expires_at,
        control_revision=control.revision, claim_token=control.claim_token,
        safety_evidence_json=canonical_json(safety), selected_action_json=canonical_json(safety.selected_action),
        safety_sha256=contract_digest(safety), selected_action_sha256=contract_digest(safety.selected_action),
        certificate_expires_at_unix_seconds=safety.certificate.expires_at_unix_seconds)
    command = AutonomousCommand(**{key: getattr(auth, key) for key in (
        "execution_id", "intent_id", "decision_id", "network_id", "workspace_id")},
        authorization=auth, resource_id="unit-lab", fence=1, installation_sha256=installation.sha256, plan=plan)
    return SimpleNamespace(control=control, observation=observation, proposal=proposal, safety=safety,
        installation=installation, provider=provider, auth=auth, command=command)


class FakeDevice:
    driver_id = "isolated-ovs-autonomous/v1"
    resource_id = "unit-lab"
    run_id = "run-1"

    def __init__(self):
        self.applied = 0
        self.restored = 0
        self.actual = "baseline"
        self.fail_apply = False
        self.fail_restore = False

    async def prepare(self, plan):
        assert self.actual == "baseline"
        return {"before": self.actual, "plan": plan}

    async def apply(self, prepared, checkpoint):
        await checkpoint()
        self.applied += 1
        self.actual = prepared["plan"]
        if self.fail_apply:
            raise RuntimeError("lost_result_after_mutation")

    async def verify(self, prepared, plan):
        if self.actual != plan:
            raise ValueError("actual_readback_mismatch")
        digest = hashlib.sha256(json.dumps(self.actual, sort_keys=True).encode()).hexdigest()
        return {"readback_sha256": digest, "readback_verified": True, "probe": {"sent": 3, "received": 3}}

    async def compensate(self, prepared, checkpoint):
        await checkpoint()
        if self.fail_restore:
            raise RuntimeError("device_unreachable")
        self.restored += 1
        self.actual = prepared["before"]
        return {"readback_sha256": hashlib.sha256(self.actual.encode()).hexdigest(), "restoration_verified": True}

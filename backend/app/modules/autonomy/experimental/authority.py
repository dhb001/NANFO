"""Public owning-service authority and independent experimental admission checks."""

from app.modules.autonomy.service import authorize

from .schemas import contract_digest, utcnow


class CurrentAuthority:
    def __init__(self, sessions, redis):
        self.sessions, self.redis = sessions, redis

    async def check(self, policy, *, write=True):
        async with self.sessions() as db:
            await self.check_in_transaction(db, policy, write=write)

    async def check_in_transaction(self, db, policy, *, write=True):
        """Owning-service reads using the final checkpoint's locked transaction.

        These public service methods read current DB authority; no lab/transport,
        model or external request is performed here. Caller bounds the transaction.
        """
        await authorize(db=db, redis=self.redis, network_id=policy.network_id,
            workspace_id=policy.workspace_id, actor_id=policy.actor_id, write=write)


def active(policy):
    if not policy.starts_at <= utcnow() < policy.expires_at:
        raise ValueError("experimental_policy_expired_or_future")


def frame_allowed(policy, frame, *, measurement_run_id=None):
    age = (utcnow() - frame.snapshot.observed_at).total_seconds()
    if (frame.runtime != policy.runtime or frame.snapshot.network_id != policy.network_id
            or frame.snapshot.workspace_id != policy.workspace_id
            or frame.snapshot.run_id != (measurement_run_id or policy.measurement_run_id or policy.run_id)
            or not 0 <= age <= policy.max_observation_age_seconds
            or frame.snapshot.published_at > utcnow()):
        raise ValueError("experimental_frame_scope_or_age_denied")


def inference_allowed(policy, frame, inference):
    r, q, p = inference.result, inference.qualification, inference.proposal
    if inference.policy_kind != policy.policy_kind or inference.frame_sha256 != contract_digest(frame):
        raise ValueError("experimental_model_binding_denied")
    if inference.policy_kind != "model":
        from .comparators import comparator_action
        action, rule = comparator_action(inference.policy_kind, frame.features)
        if (q is not None or r.action != action or r.rule != rule or r.input_sha256 != contract_digest(frame.features)
                or p.checkpoint_sha256 is not None or p.observation_contract != frame.observation.contract
                or len(policy.routes) != 2 or p.action_id != policy.routes[action].action_id
                or r.action_path != list(policy.routes[action].path)):
            raise ValueError("experimental_comparator_binding_denied")
        return policy.routes[action]
    if (inference.frame_sha256 != contract_digest(frame) or r.operation != "infer"
            or not q.qualified or q.manifest_sha256 != policy.registry_sha256
            or q.checkpoint_sha256 != policy.checkpoint_sha256
            or r.registry_sha256 != policy.registry_sha256 or r.checkpoint_sha256 != policy.checkpoint_sha256
            or r.weights_sha256 != policy.weights_sha256 or r.source_sha256 != policy.model_source_sha256
            or p.checkpoint_sha256 != policy.checkpoint_sha256
            or r.snapshot_sha256 != contract_digest(frame.snapshot)
            or r.history_sha256 != frame.snapshot.history_sha256
            or r.input_sha256 != contract_digest(frame.features)
            or r.contract_sha256 != frame.snapshot.contract_sha256 or r.spec_sha256 != frame.snapshot.spec_sha256
            or p.observation_contract != frame.observation.contract
            or q.observation_contract != frame.observation.contract
            or inference.wrapper_equivalence_sha256 != policy.wrapper_equivalence_sha256
            or inference.model_adapter_sha256 != policy.model_adapter_sha256):
        raise ValueError("experimental_model_binding_denied")
    routes = [route for route in policy.routes if route.action_id == p.action_id]
    if (len(routes) != 1 or list(routes[0].path) != r.action_path
            or policy.routes.index(routes[0]) != r.action):
        raise ValueError("experimental_route_not_allowed")
    return routes[0]


def simulation_allowed(policy, frame, inference, simulation):
    if (not simulation.admitted or simulation.frame_sha256 != contract_digest(frame)
            or simulation.inference_sha256 != contract_digest(inference)
            or simulation.policy_sha256 != contract_digest(policy)
            or simulation.action_id != inference.proposal.action_id
            or simulation.evaluator_sha256 != policy.evaluator_sha256
            or simulation.assumptions != policy.assumptions or simulation.objectives != policy.objectives):
        raise ValueError("experimental_simulation_denied")


def verification_allowed(policy, action, record):
    t, c = policy.verification, action.command
    if (record.request_id != c.request_id or record.action_sha256 != contract_digest(action)
            or record.run_id != c.run_id or record.action_id != c.route.action_id or not record.route_verified
            or not c.created_at <= record.window_started_at < record.observed_at <= utcnow()
            or (utcnow() - record.observed_at).total_seconds() > policy.max_observation_age_seconds
            or any(getattr(record, key) is None for key in (
                "goodput_mbps", "loss_fraction", "rtt_ms", "probe_sent", "probe_received", "traffic_bytes"))):
        raise ValueError("experimental_verification_unavailable_or_mismatched")
    if (record.goodput_mbps < t.min_goodput_mbps or record.loss_fraction > t.max_loss_fraction
            or record.rtt_ms > t.max_rtt_ms or record.probe_sent < t.min_probe_sent
            or not 0 <= record.probe_received <= record.probe_sent
            or record.traffic_bytes < t.min_traffic_bytes
            or 1 - record.probe_received / record.probe_sent > t.max_probe_loss_fraction):
        raise ValueError("experimental_verification_threshold_failed")

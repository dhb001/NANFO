"""Honest preregistered baseline decisions; no checkpoint/probability fabrication."""

from .schemas import BaselineProposal, ComparatorResult, InferenceRecord, contract_digest


def comparator_action(kind, features):
    if kind in ("fixed0", "fixed1"):
        return int(kind[-1]), "fixed-route/v1"
    if kind == "heuristic":
        return min(range(2), key=lambda i: (features.path_utilization[i], features.path_queue_packets[i], i)), \
            "least-utilization-then-queue/v1"
    raise ValueError("experimental_comparator_kind_invalid")


class ComparatorAdapter:
    def __init__(self, policy):
        self.policy = policy

    async def infer(self, frame):
        action, rule = comparator_action(self.policy.policy_kind, frame.features)
        if len(self.policy.routes) != 2:
            raise ValueError("experimental_comparator_two_routes_required")
        route = self.policy.routes[action]
        return InferenceRecord(policy_kind=self.policy.policy_kind, frame_sha256=contract_digest(frame),
            qualification=None, proposal=BaselineProposal(action_id=route.action_id,
                observation_contract=frame.observation.contract, evidence=[f"comparator:{rule}"]),
            result=ComparatorResult(policy_kind=self.policy.policy_kind, action=action, action_path=list(route.path),
                rule=rule, input_sha256=contract_digest(frame.features)))

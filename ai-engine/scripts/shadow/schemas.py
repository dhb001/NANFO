"""Versioned operator-file contracts. These are not backend API extensions."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

Hash = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
ID = Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}$")]
UUID = Annotated[str, Field(pattern=r"^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$")]
Text = Annotated[str, Field(min_length=1, max_length=2000)]
Number = Annotated[float, Field(ge=0, le=1e9)]
Fraction = Annotated[float, Field(ge=0, le=1)]
Action = Annotated[int, Field(ge=0, le=1)]
Method = Literal["ppo", "ospf", "constant0", "constant1", "heuristic"]
METHODS = ("ppo", "ospf", "constant0", "constant1", "heuristic")
Pair = Annotated[list[Number | None], Field(min_length=2, max_length=2)]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, allow_inf_nan=False)

    @model_validator(mode="before")
    @classmethod
    def exactLiterals(cls, value):
        if isinstance(value, dict):
            for name in (
                "live",
                "safety_authorized",
                "probabilities_are_safety_confidence",
                "production_dispatch",
                "online_learning",
                "calibrated",
            ):
                if name in value and type(value[name]) is not bool:
                    raise ValueError("boolean flag required")
            if "version" in value and type(value["version"]) is not int:
                raise ValueError("integer version required")
            # Model-before validation materializes JSON as Python values. Parse only
            # explicit ISO timestamps, retaining strict rejection of epoch numbers.
            value = dict(value)
            for name in (
                "created_at",
                "frozen_at",
                "selected_at",
                "observation_at",
                "measured_start",
                "measured_end",
                "oldest_evidence_at",
                "evaluated_at",
            ):
                if isinstance(value.get(name), str):
                    value[name] = datetime.fromisoformat(value[name])
        return value


class Scope(Record):
    network_id: UUID
    workspace_id: UUID


class Observation(Record):
    """Read-only projection of the existing V4 diagnostic evidence, with units intact."""

    path_capacity_mbps: Annotated[
        list[Annotated[float, Field(gt=0, le=100)] | None], Field(min_length=2, max_length=2)
    ]
    path_utilization: Pair
    path_queue_packets: Pair
    latency_ms: Number | None
    loss_fraction: Fraction | None
    goodput_mbps: Number | None
    offered_mbps: Annotated[float, Field(gt=0, le=1e9)]
    actual_offered_mbps: Annotated[float, Field(gt=0, le=1e9)] | None
    background_mbps: Number
    previous_action: Action
    seconds_since_change: Number


class ModelIdentity(Record):
    model_id: ID
    checkpoint_id: ID
    history_reference: ID
    registry_sha256: Hash
    policy_sha256: Hash
    checkpoint_weights_sha256: Hash
    source_sha256: Hash
    history_sha256: Hash
    input_sha256: Hash
    contract_hash: Hash
    spec_hash: Hash
    benchmark_evidence_sha256: Hash


class DiagnosticResult(ModelIdentity):
    """Exact ADR018 DiagnosticResult fields; no backend imports or inference loading."""

    action: Action
    action_path: Annotated[list[Text], Field(min_length=1, max_length=10)]
    probabilities: Annotated[list[Fraction], Field(min_length=2, max_length=2)]
    value: float
    inference_seconds: Annotated[float, Field(ge=0, le=30)]
    artifact_validation_and_inference_seconds: Annotated[float, Field(ge=0, le=30)]
    subprocess_seconds: Annotated[float, Field(ge=0, le=35)]
    evidence: Annotated[list[Observation], Field(min_length=1, max_length=3)]
    history_kind: Literal["historical_measured_v4"] = "historical_measured_v4"
    live: Literal[False] = False
    execution: Literal["not_applied"] = "not_applied"
    safety_authorized: Literal[False] = False
    probabilities_are_safety_confidence: Literal[False] = False
    benchmark_status: Literal["qualified_scoped_benchmark", "not_qualified"]
    benchmark_scope: Text
    benchmark_limitations: Annotated[list[Text], Field(min_length=1, max_length=20)]

    @model_validator(mode="after")
    def normalizedPolicy(self):
        if abs(sum(self.probabilities) - 1) > 1e-6:
            raise ValueError("invalid probabilities")
        if self.probabilities[self.action] != max(self.probabilities):
            raise ValueError("non-deterministic diagnostic action")
        return self


class Diagnostic(Scope):
    diagnostic_id: UUID
    actor_id: Text
    created_at: AwareDatetime
    result: DiagnosticResult


class ComparisonContract(Record):
    """Pins common forwarding/measurement semantics, including OSPF costs and queues."""

    spec_hash: Hash
    contract_hash: Hash
    lab_provenance_sha256: Hash
    topology_sha256: Hash
    addressing_sha256: Hash
    queues_sha256: Hash
    ospf_costs_sha256: Hash
    measurement_sha256: Hash
    mode: Literal["matched"]
    provenance: Literal["historical_measured_v4"]
    latency_metric: Literal["icmp_rtt_ms"]
    window_seconds: Annotated[float, Field(ge=2, le=10)]
    episode_steps: Annotated[int, Field(ge=2, le=64)]


class Case(Record):
    seed: Annotated[int, Field(ge=0)]
    scenario: ID
    workload_sha256: Hash
    schedule_sha256: Hash


class MethodPin(Record):
    method: Method
    policy_sha256: Hash


class Plan(Scope):
    version: Literal[1]
    purpose: Literal["historical_shadow_review"]
    frozen_at: AwareDatetime
    selected_at: AwareDatetime
    selection_split: Literal["validation"]
    train_seeds: Annotated[list[int], Field(min_length=1, max_length=10000)]
    validation_seeds: Annotated[list[int], Field(min_length=1, max_length=10000)]
    cases: Annotated[list[Case], Field(min_length=2, max_length=1000)]
    methods: Annotated[list[MethodPin], Field(min_length=5, max_length=5)]
    comparison: ComparisonContract
    model: ModelIdentity
    diagnostic_id: UUID
    diagnostic_sha256: Hash
    outcomes_sha256: Hash
    # Acquisition time, not backend replay/record creation time; pinned by the operator.
    observation_at: AwareDatetime
    action_paths: Annotated[list[list[Text]], Field(min_length=2, max_length=2)]
    allowed_actions: Annotated[list[Action], Field(min_length=1, max_length=2)]
    max_age_seconds: Annotated[float, Field(gt=0, le=31536000)]
    utilization_review_threshold: Annotated[float, Field(gt=0, le=1)]
    loss_review_threshold: Fraction

    @model_validator(mode="after")
    def predeclared(self):
        groups = [self.train_seeds, self.validation_seeds, [c.seed for c in self.cases]]
        ranges = [(1000, 1999), (2000, 2999), (3000, 3999)]
        for group, (low, high) in zip(groups, ranges, strict=True):
            if len(set(group)) != len(group) or any(not low <= seed <= high for seed in group):
                raise ValueError("duplicate or leaking split seeds")
        if set(m.method for m in self.methods) != set(METHODS):
            raise ValueError("all five frozen methods required")
        if self.frozen_at > self.selected_at:
            raise ValueError("plan must precede validation-only selection")
        if (
            self.comparison.spec_hash != self.model.spec_hash
            or self.comparison.contract_hash != self.model.contract_hash
        ):
            raise ValueError("model comparison contract mismatch")
        if (
            next(m.policy_sha256 for m in self.methods if m.method == "ppo")
            != self.model.policy_sha256
        ):
            raise ValueError("selected checkpoint mismatch")
        if (
            any(
                not 1 <= len(path) <= 10 or len(set(path)) != len(path)
                for path in self.action_paths
            )
            or self.action_paths[0] == self.action_paths[1]
        ):
            raise ValueError("invalid action paths")
        if len(set(self.allowed_actions)) != len(self.allowed_actions):
            raise ValueError("duplicate permitted action")
        return self


class Outcome(Scope):
    case: Case
    method: Method
    policy_sha256: Hash
    comparison: ComparisonContract
    split: Literal["test"]
    measured_start: AwareDatetime
    measured_end: AwareDatetime
    raw_evidence_sha256: Hash
    status: Literal["completed"]
    reward: Annotated[float, Field(ge=-1e9, le=1e9)]
    goodput_mbps: Number
    loss_fraction: Fraction
    icmp_rtt_ms: Number | None
    route_changes: Annotated[int, Field(ge=0, le=64)]


class Outcomes(Record):
    version: Literal[1]
    benchmark_evidence_sha256: Hash
    rows: Annotated[list[Outcome], Field(min_length=10, max_length=5000)]


class EvidenceSource(Record):
    kind: Literal["plan", "diagnostic", "benchmark", "outcomes", "raw_outcome"]
    sha256: Hash
    reference: Text


class Finding(Record):
    agent: ID
    status: Literal["observed", "review", "unavailable"]
    rationale: Text
    evidence_references: list[Text]
    assumptions: list[Text]


class MetricComparison(Record):
    baseline: Method
    metric: Literal["reward", "goodput_mbps", "loss_fraction", "icmp_rtt_ms", "route_changes"]
    direction: Literal["higher", "lower"]
    paired_seeds: list[int]
    missing_seeds: list[int]
    mean_policy_minus_baseline: float | None
    min_paired_difference: float | None
    max_paired_difference: float | None
    standard_error: float | None
    uncertainty: Literal["descriptive_seed_pairs_not_safety_calibration"] = (
        "descriptive_seed_pairs_not_safety_calibration"
    )


class Alternative(Record):
    option: Text
    rationale: Text
    evidence_references: list[Text]


class Freshness(Record):
    status: Literal["within_review_window", "stale", "future"]
    oldest_evidence_at: AwareDatetime
    evaluated_at: AwareDatetime
    max_age_seconds: float


class Qualification(Record):
    status: Literal["reported_scoped_benchmark_only", "not_qualified"]
    scope: Text
    limitations: list[Text]
    calibrated: Literal[False] = False
    safety_confidence: None = None


class Decision(Scope):
    version: Literal[1] = 1
    diagnostic_id: UUID
    model: ModelIdentity
    status: Literal["review", "abstain"]
    rationale: Text
    abstention_reasons: list[Text]
    diagnostic_action: Action
    diagnostic_action_path: list[Text]
    evidence: list[EvidenceSource]
    alternatives: list[Alternative]
    assumptions: list[Text]
    qualification: Qualification
    freshness: Freshness
    findings: list[Finding]
    comparisons: list[MetricComparison]
    unavailable_providers: list[Text]
    execution: Literal["not_applied"] = "not_applied"
    safety_authorized: Literal[False] = False
    production_dispatch: Literal[False] = False
    online_learning: Literal[False] = False
    probabilities_are_safety_confidence: Literal[False] = False

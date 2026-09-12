"""Independent operator dossier validation, without importing the training runtime.

This is a read-only importer, not an installer or a best.json promotion mechanism.
Operator pins authenticate the dossier selection; hashes alone do not do so.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
import zipfile
from typing import Annotated, Literal

from pydantic import Field, ValidationError, model_validator

from app.modules.autonomy.artifact_io import (
    MAX_ARTIFACT,
    SHA256,
    ArtifactRef,
    ArtifactStore,
    EvidenceError,
    StrictEvidence,
    parse_json,
)

Policy = Literal["ppo", "constant0", "constant1", "heuristic", "ospf"]
Seed = Annotated[int, Field(ge=1000, le=3999)]
Number = Annotated[float, Field(ge=0, le=1e15)]


class EvaluationPlan(StrictEvidence):
    schema_version: Literal["nanfo.matched-evaluation-plan.v1"]
    declared_at_unix_seconds: Number
    spec_sha256: SHA256
    contract_sha256: SHA256
    train_seeds: list[Seed] = Field(min_length=1, max_length=1000)
    validation_seeds: list[Seed] = Field(min_length=2, max_length=1000)
    test_seeds: list[Seed] = Field(min_length=2, max_length=1000)
    steps_per_episode: int = Field(ge=2, le=64)
    minimum_constant_margin: Annotated[float, Field(ge=0.02, le=2)]
    minimum_paired_lower_margin: Annotated[float, Field(ge=0, le=2)]

    @model_validator(mode="after")
    def splits(self):
        for values, low in (
            (self.train_seeds, 1000),
            (self.validation_seeds, 2000),
            (self.test_seeds, 3000),
        ):
            if len(values) != len(set(values)) or any(
                not low <= seed < low + 1000 for seed in values
            ):
                raise ValueError("duplicate or wrong-split seed")
        return self


class MeasuredDecision(StrictEvidence):
    """Operator-normalized complete metrics; reward is recomputed, not accepted."""

    step: int = Field(ge=1, le=64)
    action: int = Field(ge=0, le=1)
    previous_action: int = Field(ge=0, le=1)
    foreground_sent_bytes: int = Field(gt=0, le=2**63 - 1)
    foreground_received_bytes: int = Field(ge=0, le=2**63 - 1)
    foreground_sent_packets: int = Field(gt=0, le=2**63 - 1)
    foreground_received_packets: int = Field(ge=0, le=2**63 - 1)
    ping_sent: int = Field(gt=0, le=10000)
    ping_received: int = Field(ge=0, le=10000)
    latency_ms: Number | None
    max_path_utilization: Number
    max_path_queue_packets: Number
    measured_window_seconds: Annotated[float, Field(ge=2, le=12)]
    inference_seconds: Number | None
    observation_seconds: Number
    control_readback_seconds: Number
    source: ArtifactRef

    @model_validator(mode="after")
    def counts(self):
        if (
            self.foreground_received_bytes > self.foreground_sent_bytes
            or self.foreground_received_packets > self.foreground_sent_packets
            or self.ping_received > self.ping_sent
            or (self.latency_ms is None) != (self.ping_received == 0)
        ):
            raise ValueError("inconsistent measured counts or censored RTT")
        return self

    def reward(self):
        return (
            min(1.0, self.foreground_received_bytes / self.foreground_sent_bytes)
            - 0.2 * (self.latency_ms if self.latency_ms is not None else 1000) / 50
            - (1 - self.foreground_received_packets / self.foreground_sent_packets)
            - 0.1 * self.max_path_utilization
            - 0.1 * self.max_path_queue_packets / 100
            - 0.05 * (self.action != self.previous_action)
        )


class MeasuredEpisode(StrictEvidence):
    schema_version: Literal["nanfo.matched-episode.v1"]
    policy: Policy
    seed: Seed
    scenario: Literal["path0", "path1"]
    spec_sha256: SHA256
    contract_sha256: SHA256
    schedule_sha256: SHA256
    dataplane: Literal["linux-frr"]
    checkpoint_sha256: SHA256 | None
    started_at_unix_seconds: Number
    finished_at_unix_seconds: Number
    decisions: list[MeasuredDecision] = Field(min_length=2, max_length=64)

    @model_validator(mode="after")
    def complete(self):
        if self.finished_at_unix_seconds <= self.started_at_unix_seconds:
            raise ValueError("invalid episode interval")
        if [row.step for row in self.decisions] != list(
            range(1, len(self.decisions) + 1)
        ):
            raise ValueError("incomplete or duplicated decisions")
        if (self.policy == "ppo") != (self.checkpoint_sha256 is not None):
            raise ValueError("checkpoint policy mismatch")
        for prior, row in zip(self.decisions, self.decisions[1:]):
            if row.previous_action != prior.action:
                raise ValueError("discontinuous action history")
        if self.policy.startswith("constant") and any(
            row.action != int(self.policy[-1]) for row in self.decisions
        ):
            raise ValueError("constant baseline changed action")
        if self.policy == "ppo" and any(
            row.inference_seconds is None for row in self.decisions
        ):
            raise ValueError("missing actual inference timing")
        return self


class QualificationDossier(StrictEvidence):
    schema_version: Literal["nanfo.operator-qualification.v1"]
    checkpoint: ArtifactRef
    producer_qualification: ArtifactRef
    training_evidence: ArtifactRef
    plan: ArtifactRef
    spec_sha256: SHA256
    contract_sha256: SHA256
    observation_contract: str = Field(min_length=1, max_length=128)
    runtime_action: Literal["linux-frr-host-route"]
    selected_at_unix_seconds: Number
    training_rounds: int = Field(ge=0, le=100000)
    trained_transitions: int = Field(ge=0, le=100000000)
    episodes: list[ArtifactRef] = Field(min_length=20, max_length=1000)


def import_qualification(store: ArtifactStore, path: str) -> dict:
    content = store.read(path)
    digest = hashlib.sha256(content).hexdigest()
    raw = parse_json(content)
    if (
        isinstance(raw, dict)
        and type(raw.get("version")) is int
        and raw["version"] == 3
    ):
        from app.modules.autonomy.campaign_evidence import assess_producer_campaign

        return assess_producer_campaign(store, path, raw, digest)
    if isinstance(raw, dict) and "schema_version" not in raw:
        raise EvidenceError("qualification_schema_missing_not_best_pointer")
    dossier = QualificationDossier.model_validate(raw)
    checkpoint_bytes = store.referenced(dossier.checkpoint, limit=16 * 1024 * 1024)
    plan = EvaluationPlan.model_validate(parse_json(store.referenced(dossier.plan)))
    if (plan.spec_sha256, plan.contract_sha256) != (
        dossier.spec_sha256,
        dossier.contract_sha256,
    ):
        raise EvidenceError("qualification_plan_contract_mismatch")
    reasons = []
    pinned = os.environ.get("NANFO_AUTONOMY_QUALIFICATION_SHA256")
    if not pinned:
        reasons.append("operator_qualification_pin_unconfigured")
    elif pinned != digest:
        reasons.append("operator_qualification_pin_mismatch")
    producer = parse_json(store.referenced(dossier.producer_qualification))
    # Unsupported producer versions cannot be silently normalized to qualified.
    # This gate is deliberately independent of the producer's qualified boolean.
    reasons.extend(validate_producer_qualification(producer, dossier))
    producer_model = ProducerQualification.model_validate(producer)
    checkpoint_manifest = inspect_checkpoint_bytes(checkpoint_bytes)
    if checkpoint_manifest != producer_model.checkpoint.manifest:
        raise EvidenceError("checkpoint_manifest_binding_mismatch")
    if (
        dossier.training_evidence.sha256 != producer_model.training_evidence_sha256
        or checkpoint_manifest["evidence_sha256"] != dossier.training_evidence.sha256
    ):
        raise EvidenceError("training_evidence_hash_mismatch")
    store.referenced(dossier.training_evidence, limit=MAX_ARTIFACT)
    if (
        checkpoint_manifest["transitions"] != dossier.trained_transitions
        or checkpoint_manifest["training_seeds"] != plan.train_seeds
    ):
        raise EvidenceError("training_manifest_counters_or_seeds_mismatch")
    if dossier.training_rounds < 3 or dossier.trained_transitions < 144:
        reasons.append("insufficient_measured_training")
    episodes, sources, read_bytes = {}, {}, dossier.training_evidence.size_bytes
    for ref in dossier.episodes:
        read_bytes += ref.size_bytes
        if read_bytes > MAX_ARTIFACT:
            raise EvidenceError("qualification_total_bytes_exceeded")
        episode = MeasuredEpisode.model_validate(parse_json(store.referenced(ref)))
        key = episode.seed, episode.policy
        if key in episodes:
            raise EvidenceError("duplicate_evaluation_episode")
        episodes[key] = episode
        if (episode.spec_sha256, episode.contract_sha256) != (
            dossier.spec_sha256,
            dossier.contract_sha256,
        ):
            raise EvidenceError("evaluation_contract_mismatch")
        if (
            episode.policy == "ppo"
            and episode.checkpoint_sha256 != dossier.checkpoint.sha256
        ):
            raise EvidenceError("evaluation_checkpoint_mismatch")
        if len(episode.decisions) != plan.steps_per_episode:
            raise EvidenceError("evaluation_incomplete")
        if episode.started_at_unix_seconds <= plan.declared_at_unix_seconds:
            raise EvidenceError("evaluation_plan_not_predeclared")
        if episode.seed in plan.validation_seeds:
            if episode.finished_at_unix_seconds >= dossier.selected_at_unix_seconds:
                raise EvidenceError("selection_before_validation_completed")
        elif episode.seed in plan.test_seeds:
            if episode.started_at_unix_seconds <= dossier.selected_at_unix_seconds:
                raise EvidenceError("test_used_before_selection")
        else:
            raise EvidenceError("evaluation_seed_not_reserved")
        for decision in episode.decisions:
            ref = decision.source
            if ref.path in sources and sources[ref.path] != ref:
                raise EvidenceError("evaluation_source_identity_conflict")
            sources[ref.path] = ref
    read_bytes += sum(ref.size_bytes for ref in sources.values())
    if read_bytes > MAX_ARTIFACT or len(sources) > 1000:
        raise EvidenceError("qualification_total_bytes_exceeded")
    for ref in sources.values():
        store.referenced(ref)
    # These normalized records remain an independent inspection format until a
    # concrete raw producer parser validates their measurement derivation.
    reasons.append("normalized_measurement_derivation_unverified")
    policies = ("ppo", "constant0", "constant1", "heuristic", "ospf")
    expected = {
        (seed, policy)
        for seed in [*plan.validation_seeds, *plan.test_seeds]
        for policy in policies
    }
    if set(episodes) != expected:
        raise EvidenceError("matched_baselines_incomplete")
    comparisons = {}
    for split, seeds in (
        ("validation", plan.validation_seeds),
        ("test", plan.test_seeds),
    ):
        scenarios = [episodes[seed, "ppo"].scenario for seed in seeds]
        if scenarios.count("path0") != scenarios.count("path1"):
            raise EvidenceError("heldout_scenarios_unbalanced")
        for seed in seeds:
            matched = [episodes[seed, policy] for policy in policies]
            if len({(row.scenario, row.schedule_sha256) for row in matched}) != 1:
                raise EvidenceError("matched_schedule_mismatch")
        means = {
            policy: [
                sum(row.reward() for row in episodes[seed, policy].decisions)
                / plan.steps_per_episode
                for seed in seeds
            ]
            for policy in policies
        }
        comparisons[split] = {}
        actions = {
            row.action for seed in seeds for row in episodes[seed, "ppo"].decisions
        }
        if actions != {0, 1}:
            reasons.append("heldout_policy_not_action_dependent")
        for policy in policies[1:]:
            differences = [
                a - b for a, b in zip(means["ppo"], means[policy], strict=True)
            ]
            mean = sum(differences) / len(differences)
            variance = sum((value - mean) ** 2 for value in differences) / (
                len(differences) - 1
            )
            # Diagnostic normal approximation, not a small-sample safety confidence.
            lower = mean - 1.96 * math.sqrt(variance / len(differences))
            comparisons[split][policy] = {
                "paired_mean_reward_difference": mean,
                "normal_approximation_lower_95": lower,
                "pairs": len(seeds),
            }
            if policy.startswith("constant") and (
                mean <= plan.minimum_constant_margin
                or lower <= plan.minimum_paired_lower_margin
            ):
                reasons.append("heldout_constant_advantage_not_established")
    return {
        "schema_version": "nanfo.qualification-assessment.v1",
        "qualified": not reasons,
        "manifest_sha256": digest,
        "checkpoint_sha256": dossier.checkpoint.sha256,
        "spec_sha256": dossier.spec_sha256,
        "contract_sha256": dossier.contract_sha256,
        "observation_contract": dossier.observation_contract,
        "runtime_action": dossier.runtime_action,
        "reasons": list(dict.fromkeys(reasons)),
        "comparisons": comparisons,
        "installed": False,
        "production_dispatch": False,
    }


class CheckpointIdentity(StrictEvidence):
    checkpoint_sha256: SHA256
    manifest: dict


class CheckpointManifest(StrictEvidence):
    version: Annotated[int, Field(ge=3, le=3)]
    contract_hash: SHA256
    contract: dict
    config: dict
    provenance: Literal["measured-lab"]
    training_seeds: list[Annotated[int, Field(ge=1000, le=1999)]] = Field(
        min_length=1, max_length=1000
    )
    updates: int = Field(ge=1, le=10**9)
    transitions: int = Field(ge=2, le=10**9)
    episodes: int = Field(ge=1, le=1000)
    versions: dict[str, str]
    weights_sha256: SHA256
    evidence_sha256: SHA256
    environment_spec: dict
    spec_hash: SHA256
    training_distribution: dict
    compatibility_hash: SHA256
    lab_provenance: dict
    client_source_files: dict[str, SHA256] = Field(min_length=1, max_length=64)


def inspect_checkpoint_bytes(content: bytes):
    """Validate bounded ZIP_STORED metadata and tensor bytes, never unpickle them."""
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
            if (
                len(entries) != 2
                or {row.filename for row in entries} != {"manifest.json", "weights.pt"}
                or any(
                    row.compress_type != zipfile.ZIP_STORED or row.flag_bits & 1
                    for row in entries
                )
                or sum(row.file_size for row in entries) > 16 * 1024 * 1024
                or archive.getinfo("manifest.json").file_size > 128 * 1024
            ):
                raise EvidenceError("checkpoint_archive_invalid")
            raw = parse_json(archive.read("manifest.json"))
            manifest = CheckpointManifest.model_validate(raw)
            weights = archive.read("weights.pt")

        def digest(value):
            return hashlib.sha256(
                json.dumps(
                    value, sort_keys=True, separators=(",", ":"), allow_nan=False
                ).encode()
            ).hexdigest()

        if (
            hashlib.sha256(weights).hexdigest() != manifest.weights_sha256
            or digest(manifest.contract) != manifest.contract_hash
            or digest(manifest.environment_spec) != manifest.spec_hash
            or digest(
                {
                    "contract_hash": manifest.contract_hash,
                    "environment_spec": manifest.environment_spec,
                    "spec_hash": manifest.spec_hash,
                    "training_distribution": manifest.training_distribution,
                }
            )
            != manifest.compatibility_hash
        ):
            raise EvidenceError("checkpoint_internal_hash_mismatch")
        if (
            manifest.episodes != len(manifest.training_seeds)
            or len(manifest.training_seeds) != len(set(manifest.training_seeds))
            or manifest.training_distribution.get("mode") != "matched"
            or manifest.contract.get("version") != 3
            or not manifest.lab_provenance.get("lab_image_id")
        ):
            raise EvidenceError("checkpoint_training_contract_invalid")
        return raw
    except (zipfile.BadZipFile, KeyError, RuntimeError) as exc:
        raise EvidenceError("checkpoint_archive_invalid") from exc


class DirectionalDependence(StrictEvidence):
    desired_route_fraction: Annotated[float, Field(ge=0, le=1)]
    pressure_swap_desired_route_fraction: Annotated[float, Field(ge=0, le=1)]
    swap_is_diagnostic_not_measured_reward: bool


class PairedSeed(StrictEvidence):
    seed: Annotated[int, Field(ge=2000, le=2999)]
    policy: float
    baseline: float
    delta: float

    @model_validator(mode="after")
    def difference(self):
        if not math.isclose(self.policy - self.baseline, self.delta, abs_tol=1e-12):
            raise ValueError("paired difference mismatch")
        return self


class PairedMetric(StrictEvidence):
    pairs: list[PairedSeed] = Field(max_length=1000)
    paired_seed_count: int = Field(ge=0, le=1000)
    mean_delta: float | None
    ci95: Annotated[list[float], Field(min_length=2, max_length=2)] | None
    method: Literal["paired seed-mean Student-t interval; normality assumption"]
    limitation: str = Field(max_length=512)

    @model_validator(mode="after")
    def summary(self):
        if self.paired_seed_count != len(self.pairs) or len(
            {p.seed for p in self.pairs}
        ) != len(self.pairs):
            raise ValueError("paired count mismatch")
        if self.pairs:
            mean = sum(p.delta for p in self.pairs) / len(self.pairs)
            if self.mean_delta is None or not math.isclose(
                mean, self.mean_delta, abs_tol=1e-12
            ):
                raise ValueError("paired mean mismatch")
        elif self.mean_delta is not None:
            raise ValueError("empty paired mean")
        if self.ci95 is not None and (
            self.mean_delta is None
            or not self.ci95[0] <= self.mean_delta <= self.ci95[1]
        ):
            raise ValueError("invalid uncertainty interval")
        return self


class ProducerEvidencePaths(StrictEvidence):
    checkpoint: str = Field(min_length=1, max_length=512)
    training: str = Field(min_length=1, max_length=512)
    validation: list[str] = Field(min_length=5, max_length=5)
    plan: str = Field(min_length=1, max_length=512)
    calibration: list[str] = Field(min_length=2, max_length=2)


class ProducerQualification(StrictEvidence):
    version: Annotated[int, Field(ge=3, le=3)]
    qualified: bool
    scope: Literal["useful adaptation on validation only"]
    checkpoint: CheckpointIdentity
    plan_sha256: SHA256
    training_evidence_sha256: SHA256
    train_only_action_effects: dict[Literal["path0", "path1"], float]
    calibration_evidence_sha256: dict[Literal["constant0", "constant1"], SHA256]
    evidence_paths: ProducerEvidencePaths
    validation_evidence_sha256: dict[Policy, SHA256]
    minimum_margin_exclusive: Annotated[float, Field(ge=0.02, le=0.02)]
    margins_over_both_constants: dict[Literal["constant0", "constant1"], float]
    directional_dependence: dict[Literal["path0", "path1"], DirectionalDependence]
    comparisons: dict[
        Policy,
        dict[
            Literal["reward", "goodput_mbps", "loss_fraction", "icmp_rtt_ms"],
            PairedMetric,
        ],
    ]
    validation_mean_reward: float
    test_status: Literal["not assessed; freeze selection before fresh holdout"]
    autonomous_dispatch: Literal["blocked"]
    safety_guarantee: bool
    limitation: str = Field(max_length=512)

    @model_validator(mode="after")
    def scopes(self):
        if (
            set(self.validation_evidence_sha256)
            != {"ppo", "constant0", "constant1", "heuristic", "ospf"}
            or set(self.comparisons) != {"constant0", "constant1", "heuristic", "ospf"}
            or set(self.margins_over_both_constants) != {"constant0", "constant1"}
            or set(self.directional_dependence) != {"path0", "path1"}
            or set(self.train_only_action_effects) != {"path0", "path1"}
            or set(self.calibration_evidence_sha256) != {"constant0", "constant1"}
            or self.safety_guarantee
        ):
            raise ValueError("incomplete or unsafe producer qualification scope")
        for metrics in self.comparisons.values():
            if set(metrics) != {
                "reward",
                "goodput_mbps",
                "loss_fraction",
                "icmp_rtt_ms",
            }:
                raise ValueError("incomplete producer comparison metrics")
        return self


def validate_producer_qualification(value, dossier: QualificationDossier | None):
    producer = ProducerQualification.model_validate(value)
    reasons = []
    if (
        dossier is not None
        and producer.checkpoint.checkpoint_sha256 != dossier.checkpoint.sha256
    ):
        raise EvidenceError("producer_checkpoint_mismatch")
    manifest = producer.checkpoint.manifest
    # Manifest is bounded JSON but not deserialized as Python/tensors. Until its
    # full raw training derivation is verified it cannot confer qualification.
    if (
        type(manifest.get("version")) is not int
        or manifest["version"] != 3
        or manifest.get("provenance") != "measured-lab"
    ):
        reasons.append("checkpoint_manifest_not_measured_matched_v3")
    if dossier is not None and (
        manifest.get("spec_hash"),
        manifest.get("contract_hash"),
    ) != (dossier.spec_sha256, dossier.contract_sha256):
        raise EvidenceError("producer_manifest_contract_mismatch")
    for name, margin in producer.margins_over_both_constants.items():
        comparison = producer.comparisons[name]["reward"]
        if comparison.mean_delta != margin:
            raise EvidenceError("producer_margin_comparison_mismatch")
        if margin <= 0.02:
            reasons.append("heldout_constant_advantage_not_established")
        if (
            comparison.paired_seed_count < 2
            or comparison.ci95 is None
            or comparison.ci95[0] <= 0
        ):
            reasons.append("paired_improvement_uncertain")
    if any(
        row.desired_route_fraction <= 0.5
        or row.pressure_swap_desired_route_fraction <= 0.5
        or not row.swap_is_diagnostic_not_measured_reward
        for row in producer.directional_dependence.values()
    ):
        reasons.append("heldout_policy_not_action_dependent")
    if not producer.qualified:
        reasons.append("producer_model_unqualified")
    return reasons


def assessment_error(exc: Exception, kind: str):
    if isinstance(exc, EvidenceError):
        reason = str(exc)
    elif isinstance(exc, ValidationError):
        reason = f"{kind}_schema_invalid"
    else:
        reason = f"{kind}_validation_failed"
    result = {"qualified": False, "reasons": [reason]}
    if isinstance(exc, ValidationError):
        # Do not echo attacker-chosen extra-field names or evidence values.
        result["validation_errors"] = [error["type"] for error in exc.errors()[:20]]
    return result

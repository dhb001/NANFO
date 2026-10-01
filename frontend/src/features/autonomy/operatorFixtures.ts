import { autonomyFixture } from "./fixtures";
import type { ModelDiagnostic, ModelDiagnostics } from "./modelTypes";
import type { Configuration } from "./configurationTypes";
import type { TimedOverride } from "./overrideTypes";
import type { IntentDetailResult } from "../../shared/types/intent";

const scope = autonomyFixture();
export function modelRecordFixture(): ModelDiagnostic {
  return { diagnostic_id: "10000000-0000-4000-8000-000000000001", network_id: scope.network_id, workspace_id: scope.workspace_id,
    actor_id: "operator", created_at: "2026-09-10T12:00:00Z", result: {
      model_id: "pinned-model", checkpoint_id: "frozen-checkpoint", history_reference: "measured-history-1",
      registry_sha256: "a".repeat(64), policy_sha256: "b".repeat(64), checkpoint_weights_sha256: "c".repeat(64),
      source_sha256: "d".repeat(64), history_sha256: "e".repeat(64), input_sha256: "f".repeat(64),
      contract_hash: "1".repeat(64), spec_hash: "2".repeat(64), action: 1, action_path: ["s1", "s3", "s4"], probabilities: [0.2, 0.8], value: 0.4,
      inference_seconds: 0.003, artifact_validation_and_inference_seconds: 0.02, subprocess_seconds: 1.2,
      evidence: [{ observed_goodput_mbps: 4 }], history_kind: "historical_measured_v4", live: false, execution: "not_applied",
      safety_authorized: false, probabilities_are_safety_confidence: false,
      benchmark_status: "qualified_scoped_benchmark", benchmark_scope: "Recorded isolated benchmark",
      benchmark_limitations: ["Not calibrated production autonomy"], benchmark_evidence_sha256: "3".repeat(64),
    } };
}
export function modelFixture(): ModelDiagnostics {
  return { network_id: scope.network_id, workspace_id: scope.workspace_id, status: "operator_registered", reasons: [],
    model: { model_id: "pinned-model", checkpoint_id: "frozen-checkpoint", checkpoint_sha256: "b".repeat(64),
      history_references: ["measured-history-1"], status: "operator_registered", benchmark_status: "qualified_scoped_benchmark",
      benchmark_scope: "Recorded isolated benchmark", benchmark_limitations: ["Not calibrated production autonomy"] },
    diagnostics: [modelRecordFixture()], live_history_status: "unavailable", safety_authorized: false, production_dispatch: false };
}

export function configurationFixture(): Configuration {
  return { network_id: scope.network_id, workspace_id: scope.workspace_id, revision: 1, control_revision: 0,
    operational: { max_observation_age_seconds: 30, decision_interval_seconds: 10, min_route_hold_seconds: 3, max_changes_per_minute: 10,
      min_confidence: 0.95, allow_uncalibrated_confidence: false },
    requested_training: { reward_weights: { goodput: 1 } }, effective_training: null, training_status: "retraining_required",
    effective_training_status: "model_owned_unavailable", safety_merge: "stricter_than_calibrated_policy", history_limit: 100,
    allow_uncalibrated_confidence_honoured: false,
    history: [{ revision: 1, actor_id: "operator", reason: "Initial requested settings", content_sha256: "a".repeat(64), created_at: "2026-09-10T12:00:00Z",
      operational: { max_observation_age_seconds: 30, decision_interval_seconds: 10, min_route_hold_seconds: 3, max_changes_per_minute: 10,
        min_confidence: 0.95, allow_uncalibrated_confidence: false }, training: { reward_weights: { goodput: 1 } } }] };
}
export function overrideFixture(patch: Partial<TimedOverride> = {}): TimedOverride {
  return { override_id: "20000000-0000-4000-8000-000000000001", network_id: scope.network_id, workspace_id: scope.workspace_id,
    intent_id: "20000000-0000-4000-8000-000000000002", execution_id: "20000000-0000-4000-8000-000000000003",
    actor_id: "operator", reason: "Temporary maintenance", duration_seconds: 300, return_mode: "monitor", prior_mode: "recommend", prior_revision: 0, hold_revision: 1,
    checkpoint_sha256: null, prior_approval_expires_at: null, prior_approved_by_user_id: null,
    command_sha256: "a".repeat(64), plan_hash: "b".repeat(64), binding_digest: "c".repeat(64), run_id: "20000000-0000-4000-8000-000000000004",
    configuration_verified_at: "2026-09-10T12:00:00Z", evidence_scope: "historical_configuration_readback", status: "holding", reasons: [],
    cancellation_id: null, cancellation_requested_at: null, cancelled_by_user_id: null, restoration_attempts: 0, verification: null, restored_at: null,
    return_requested_at: null, return_requested_by_user_id: null, return_reason: null, returned_at: null,
    expires_at: "2026-09-10T12:05:00Z", created_at: "2026-09-10T12:00:00Z", updated_at: "2026-09-10T12:00:00Z", ...patch };
}

export function overrideIntentFixture(actorId: string): IntentDetailResult {
  const row = overrideFixture();
  return { intent_id: row.intent_id, workspace_id: row.workspace_id, network_id: row.network_id, requested_by_user_id: actorId,
    status: "execution_completed", intent_kind: "structured", intent_payload: {}, validation_result: {}, explainability: {},
    confidence: { score: 0, band: "unavailable", approval_required: true }, idempotency_key: null, queue_status: "completed",
    stream_entry_id: null, warning: null, correlation_id: "fixture", requested_at: row.created_at, created_at: row.created_at, updated_at: row.created_at,
    execution_provenance: { execution_id: row.execution_id, approved_by_user_id: actorId, phase: "completed", verification: { readback_verified: true, readback_sha256: "a".repeat(64) } } };
}

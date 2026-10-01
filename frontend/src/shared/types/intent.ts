import type { Schema } from "@/shared/types/contracts";

export type IntentValidationReason = Schema<"ValidationReason">;

/** Exact lab identity an operator approves; echo it verbatim on execute (ADR-028 C3). */
export type ApprovalBinding = Schema<"ApprovalBinding">;

/** Copy verbatim into `scenario_config.action_binding` for the pre-execution simulation (C18). */
export type SimulationActionBinding = Schema<"SimulationActionBinding">;

export interface IntentValidationState {
  is_valid: boolean;
  reasons?: IntentValidationReason[];
  required_checks?: string[];
  capability_match: string;
  dependency_analysis: string;
  simulation_required: boolean;
  policy_reference: string;
  validated_at: string;
  /** "baseline_schema_only" unless model-backed validation actually ran; disclose it. */
  validation_kind?: string;
  /** "unavailable" when no model evidence backs the validation. */
  model_evidence?: string;
}

export interface IntentExplainability {
  summary: string;
  evidence?: string[];
  alternatives_considered?: string[];
  policy_reference: string;
}

export interface IntentConfidenceState {
  score: number;
  band: string;
  approval_required: boolean;
}

export interface ValidateIntentResult {
  intent_id: string;
  workspace_id: string;
  network_id: string | null;
  status: string;
  intent_kind: string;
  validation: IntentValidationState;
  explainability: IntentExplainability;
  confidence: IntentConfidenceState;
  idempotency_key: string | null;
  correlation_id: string;
  requested_at: string;
  queue_status: string;
  stream_entry_id?: string | null;
  warning?: string | null;
  /** The stored intent was returned for a repeated Idempotency-Key (C3). */
  idempotent_replay?: boolean;
  approval_binding?: ApprovalBinding | null;
  simulation_action_binding?: SimulationActionBinding | null;
}

export interface ExecuteIntentResult {
  intent_id: string;
  workspace_id: string;
  network_id: string | null;
  status: string;
  intent_kind: string;
  queue_status: string;
  stream_entry_id: string | null;
  warning: string | null;
  validation_result: Record<string, unknown>;
  execution_provenance: Record<string, unknown>;
  explainability: Record<string, unknown>;
  confidence: IntentConfidenceState;
  idempotency_key: string | null;
  correlation_id: string;
  requested_by_user_id: string;
  requested_at: string;
  updated_at: string;
  idempotent_replay: boolean;
  approval_binding?: ApprovalBinding | null;
}

export interface IntentDetailResult {
  intent_id: string;
  workspace_id: string;
  network_id: string | null;
  status: string;
  intent_kind: string;
  intent_payload: Record<string, unknown>;
  validation_result: Record<string, unknown>;
  execution_provenance: Record<string, unknown>;
  explainability: Record<string, unknown>;
  confidence: IntentConfidenceState;
  idempotency_key: string | null;
  queue_status: string;
  stream_entry_id: string | null;
  warning: string | null;
  correlation_id: string;
  requested_by_user_id: string;
  requested_at: string;
  created_at: string;
  updated_at: string;
  approval_binding?: ApprovalBinding | null;
  simulation_action_binding?: SimulationActionBinding | null;
}

export interface ValidateIntentRequest {
  workspace_id: string;
  network_id?: string;
  intent: Record<string, unknown>;
}

export interface ExecuteIntentRequest {
  simulation_id?: string;
  workspace_id: string;
  intent_id: string;
  /** The selected intent's stored key (or omitted); a different key is 409 INTENT_IDEMPOTENCY_CONFLICT. */
  idempotency_key?: string;
  manual_approval?: boolean;
  cancel?: boolean;
  /** Current server binding from validate/detail; stale values are 409 APPROVAL_BINDING_MISMATCH. */
  approval_binding?: ApprovalBinding | null;
}
export interface IntentSummary {
  intent_id: string;
  network_id: string | null;
  workspace_id: string;
  action: string | null;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface IntentHistory {
  items: IntentSummary[];
  total: number;
  page: number;
  page_size: number;
}

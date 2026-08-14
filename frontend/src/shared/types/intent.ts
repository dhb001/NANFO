export interface IntentValidationReason {
  code: string;
  message: string;
  path?: string;
}

export interface IntentValidationState {
  is_valid: boolean;
  reasons: IntentValidationReason[];
  required_checks: string[];
  capability_match: string;
  dependency_analysis: string;
  simulation_required: boolean;
  policy_reference: string;
  validated_at: string;
}

export interface IntentExplainability {
  summary: string;
  evidence: string[];
  alternatives_considered: string[];
  policy_reference: string;
  execution_posture?: string;
  execution_summary?: string;
  failure_reason?: string;
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
  stream_entry_id: string | null;
  warning: string | null;
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
}

export interface ValidateIntentRequest {
  workspace_id: string;
  network_id?: string;
  intent: Record<string, unknown>;
}

export interface ExecuteIntentRequest {
  workspace_id: string;
  intent_id: string;
  idempotency_key?: string;
}

// ADR-012 request contract. No model paths or client-supplied safety bounds.
export type AutonomyMode = "monitor" | "recommend" | "autonomous";

export interface AutonomyUpdate {
  network_id: string;
  expected_revision: number;
  mode: AutonomyMode;
  checkpoint_sha256: string | null;
  approval_expires_at: string | null;
}

/**
 * Typed proposal confidence (ADR-028 C17). `calibrated` is authoritative: a raw policy
 * probability is never calibrated, and `calibration_id` is present exactly when it is.
 */
export interface AutonomyConfidence {
  value: number;
  method: string;
  calibrated: boolean;
  calibration_id?: string | null;
}

/** C25 two-person switch: a request awaiting a different approver's identical PUT. */
export interface AutonomyPendingApproval {
  requested_by_user_id: string;
  mode: AutonomyMode;
  expected_revision: number;
  checkpoint_sha256: string | null;
  approval_expires_at: string | null;
  requested_at: string;
  expires_at: string;
}

export interface AutonomyProvider {
  provider_id: string;
  status: "ready" | "unavailable" | "incompatible" | "uncalibrated";
  reasons: string[];
}

export interface AutonomyObservation {
  network_id: string;
  workspace_id: string;
  provider_id: string;
  contract: string;
  observed_at: string | null;
  collected_at: string;
  age_seconds: number | null;
  fresh: boolean;
  compatible: boolean;
  reasons: string[];
  evidence: string[];
  samples: { record_id: string; device_id: string; metric: string; value: number; unit: string | null;
    observed_at: string; source: string; run_id: string | null; port_no: string | null }[];
  /** History summaries omit samples and report their count. */
  sample_count?: number;
}

export interface AutonomyDecision {
  decision_id: string;
  network_id: string;
  workspace_id: string;
  actor_id: string;
  mode: AutonomyMode;
  control_revision: number;
  status: "observing" | "observed" | "blocked" | "recommended" | "accepted" | "verified" | "uncertain" | "cancelled" | "failed" | "control_changed" | "stopped";
  reasons: string[];
  checkpoint_sha256: string | null;
  observation: AutonomyObservation | null;
  proposal: { action_id: string; checkpoint_sha256: string; observation_contract: string; evidence: string[]; confidence?: AutonomyConfidence | null } | null;
  /** The persisted proposal's confidence (absent for pre-C17 history and decisions without a proposal). */
  confidence?: AutonomyConfidence | null;
  /** Identical no-change cycles this row stands for. */
  repeat_count?: number;
  last_seen_at?: string | null;
  projection?: "full" | "summary";
  safety: { admissible: boolean; action_id: string | null; model_version: string; reasons: string[]; evidence: string[];
    certificate?: SafetyCertificate | null; binding?: SafetyBinding | null } | null;
  evidence: string[];
  execution_id: string | null;
  verification: { execution_id: string; status: "pending" | "verified" | "cancelled" | "failed" | "uncertain"; safe_to_release: boolean; evidence: string[]; reasons: string[] } | null;
  created_at: string;
  updated_at: string;
}

export interface SafetyCertificate {
  model: "bounded-fluid-v1";
  calibration_id: string;
  provider_id: string;
  policy_version: string;
  input_sha256: string;
  network_id: string;
  run_id: string;
  snapshot_id: string;
  action_id: string;
  routes: { demand_id: string; route_id: string }[];
  conditional: true;
  observed_at_unix_seconds: number;
  horizon_end_unix_seconds: number;
  dt_seconds: number;
  actuation_delay_upper_seconds: number;
  expires_at_unix_seconds: number;
  drift: { v_before_bytes_squared: number; v_next_upper_bytes_squared: number; upper_bytes_squared: number; budget_bytes_squared: number };
  envelope: { threshold_bytes: number; q_next_upper_bytes: Record<string, number> };
  model_checks_passed: boolean;
}

// Read-only fields consumed from the backend SafetyBinding; nested provider inputs are not UI controls.
export interface SafetyBinding {
  workspace_id: string;
  observation_sha256: string;
  proposal_sha256: string;
  calibration_sha256: string;
  selected_action_sha256: string;
  evaluated_at_unix_seconds: number;
}

// backend/app/modules/autonomy/schemas.py: AutonomyResponse (ADR-012).
export interface AutonomyStatus {
  network_id: string;
  workspace_id: string;
  mode: AutonomyMode;
  status: "monitoring" | "ready" | "blocked" | "stopped" | "executing" | "uncertain";
  ready: boolean;
  blocked_reasons: string[];
  online_learning: false;
  production_dispatch: false;
  checkpoint_sha256: string | null;
  approval_expires_at: string | null;
  approved_by_user_id: string | null;
  emergency_stopped: boolean;
  stopped_at: string | null;
  stopped_by_user_id: string | null;
  active_execution_id: string | null;
  cancellation_status: "none" | "requested" | "verified" | "uncertain";
  revision: number;
  providers: Record<"observer" | "qualification" | "inference" | "safety" | "executor", AutonomyProvider>;
  last_observation: AutonomyObservation | null;
  last_decision: AutonomyDecision | null;
  decisions: AutonomyDecision[];
  history_limit: number;
  updated_at: string | null;
  pending_approval?: AutonomyPendingApproval | null;
}

/** PUT /autonomy result: 202 + meta.pending_approval records the first of two approvals (C25). */
export interface AutonomyUpdateResult {
  status: AutonomyStatus;
  pendingApproval: boolean;
  pendingApprovalExpiresAt: string | null;
}

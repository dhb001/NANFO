import type { AutonomyMode } from "./types";
// backend/app/modules/autonomy/schemas.py: ADR018 override public contracts.
export interface TimedOverride {
  override_id: string; network_id: string; workspace_id: string; intent_id: string; execution_id: string;
  actor_id: string; reason: string; duration_seconds: number; return_mode: AutonomyMode; prior_mode: AutonomyMode;
  prior_revision: number; hold_revision: number; checkpoint_sha256: string | null;
  prior_approval_expires_at: string | null; prior_approved_by_user_id: string | null;
  command_sha256: string; plan_hash: string; binding_digest: string; run_id: string;
  configuration_verified_at: string; evidence_scope: "historical_configuration_readback";
  status: "holding" | "restoring" | "restored" | "return_blocked" | "returned"; reasons: string[];
  cancellation_id: string | null; cancellation_requested_at: string | null; cancelled_by_user_id: string | null;
  restoration_attempts: number; verification: Record<string, unknown> | null; restored_at: string | null;
  return_requested_at: string | null; return_requested_by_user_id: string | null; return_reason: string | null;
  returned_at: string | null; expires_at: string; created_at: string; updated_at: string;
}
export interface OverrideList { network_id: string; control_revision: number; overrides: TimedOverride[]; history_limit: number }
export interface OverrideCreate {
  network_id: string; intent_id: string; execution_id: string; expected_revision: number;
  reason: string; duration_seconds: number; return_mode: AutonomyMode;
}

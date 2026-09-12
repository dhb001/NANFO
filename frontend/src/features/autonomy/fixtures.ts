import type { AutonomyDecision, AutonomyStatus, SafetyCertificate } from "./types";

export function certificateFixture(): SafetyCertificate {
  return {
    model: "bounded-fluid-v1", calibration_id: "test-calibration", provider_id: "test-only", policy_version: "test-policy",
    input_sha256: "a".repeat(64), network_id: "00000000-0000-0000-0000-000000000333", run_id: "test-run", snapshot_id: "test-snapshot",
    action_id: "route-1", routes: [{ demand_id: "test-demand", route_id: "route-1" }], conditional: true,
    observed_at_unix_seconds: 1_000, horizon_end_unix_seconds: 1_010, dt_seconds: 10,
    actuation_delay_upper_seconds: 1, expires_at_unix_seconds: 1_005,
    drift: { v_before_bytes_squared: 50, v_next_upper_bytes_squared: 32, upper_bytes_squared: -18, budget_bytes_squared: 0 },
    envelope: { threshold_bytes: 20, q_next_upper_bytes: { "test-egress": 8 } }, model_checks_passed: true,
  };
}

export function readyProvidersFixture(): AutonomyStatus["providers"] {
  const provider = { provider_id: "test-only", status: "ready" as const, reasons: [] };
  return { observer: provider, qualification: provider, inference: provider, safety: provider, executor: provider };
}

export function decisionFixture(overrides: Partial<AutonomyDecision> = {}): AutonomyDecision {
  return {
    decision_id: "00000000-0000-0000-0000-000000000555",
    network_id: "00000000-0000-0000-0000-000000000333",
    workspace_id: "00000000-0000-0000-0000-000000000222",
    actor_id: "test-operator", mode: "recommend", control_revision: 1, status: "blocked",
    reasons: ["qualified_checkpoint_unavailable"], checkpoint_sha256: null,
    observation: null, proposal: null, safety: null, evidence: [], execution_id: null, verification: null,
    created_at: "2026-09-09T12:00:00Z", updated_at: "2026-09-09T12:00:00Z", ...overrides,
  };
}

// Deterministic schema fixture for unit/component/browser tests, never an API fallback.
export function autonomyFixture(overrides: Partial<AutonomyStatus> = {}): AutonomyStatus {
  return {
    network_id: "00000000-0000-0000-0000-000000000333",
    workspace_id: "00000000-0000-0000-0000-000000000222",
    mode: "monitor", status: "monitoring", ready: false,
    blocked_reasons: ["qualified_checkpoint_unavailable", "observation_contract_incompatible", "frozen_inference_unavailable", "calibrated_safety_unavailable", "autonomous_executor_unavailable"],
    online_learning: false, production_dispatch: false,
    checkpoint_sha256: null, approval_expires_at: null, approved_by_user_id: null,
    emergency_stopped: false, stopped_at: null, stopped_by_user_id: null,
    active_execution_id: null, cancellation_status: "none", revision: 0,
    providers: {
      observer: { provider_id: "adr009_history_v1", status: "incompatible", reasons: ["observation_contract_incompatible"] },
      qualification: { provider_id: "uninstalled", status: "unavailable", reasons: ["qualified_checkpoint_unavailable"] },
      inference: { provider_id: "uninstalled", status: "unavailable", reasons: ["frozen_inference_unavailable"] },
      safety: { provider_id: "uninstalled", status: "uncalibrated", reasons: ["calibrated_safety_unavailable"] },
      executor: { provider_id: "uninstalled", status: "unavailable", reasons: ["autonomous_executor_unavailable"] },
    },
    last_observation: null, last_decision: null, decisions: [], history_limit: 20, updated_at: null,
    ...overrides,
  };
}

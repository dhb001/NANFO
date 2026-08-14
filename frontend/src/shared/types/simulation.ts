export interface ScenarioValidationState {
  pipeline_stage: string;
  required_checks: string[];
  policy_reference: string;
  status: string;
  queued_at: string;
  requested_by_user_id: string;
}

export interface SimulationValidationHandoff {
  simulation_id: string;
  resumed_from_simulation_id: string | null;
  scenario_id: string;
  network_id: string;
  scene_object_id: string;
  state: string;
  status: string;
  risk_gate: string;
  scenario_name: string;
  validation: ScenarioValidationState;
  requested_at: string;
  correlation_id: string;
  queue_status: string;
  stream_entry_id: string | null;
  warning: string | null;
}

export interface PauseSimulationResult {
  simulation_id: string;
  network_id: string;
  scene_object_id: string;
  state: string;
  status: string;
  risk_gate: string;
  scenario_id: string;
  correlation_id: string;
}

export interface BranchSimulationResult {
  simulation_id: string;
  parent_simulation_id: string;
  scenario_id: string;
  network_id: string;
  scene_object_id: string;
  state: string;
  status: string;
  risk_gate: string;
  scenario_name: string;
  validation: ScenarioValidationState;
  requested_at: string;
  correlation_id: string;
}

export interface SimulationDetail {
  simulation_id: string;
  parent_simulation_id: string | null;
  scenario_id: string;
  network_id: string;
  workspace_id: string;
  scene_object_id: string;
  state: string;
  status: string;
  risk_gate: string;
  scenario_name: string;
  validation: Record<string, unknown>;
  run_output: Record<string, unknown>;
  model_versions: Record<string, unknown>;
  audit_provenance: Record<string, unknown>;
  queue_status: string;
  stream_entry_id: string | null;
  warning: string | null;
  requested_by_user_id: string;
  requested_at: string;
  created_at: string;
  updated_at: string;
}

export interface SimulationMetricsSnapshot {
  latency_ms: number;
  loss_pct: number;
  throughput_mbps: number;
}

export interface SimulationCompare {
  simulation_id: string;
  baseline_simulation_id: string;
  scenario_id: string;
  baseline_scenario_id: string;
  network_id: string;
  simulation_metrics: SimulationMetricsSnapshot;
  baseline_metrics: SimulationMetricsSnapshot;
  deltas: SimulationMetricsSnapshot;
}

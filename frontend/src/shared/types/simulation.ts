export interface ScenarioValidationState {
  source?: "operator_configured_model" | "unavailable";
  physical_safety_authorized?: false;
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
  scenario_config?: ScenarioConfig | null;
  progress?: { tick: number; duration_ticks: number } | null;
  evidence_expires_at?: string | null;
  revision?: number;
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
  latency_ms: number | null;
  loss_pct: number | null;
  throughput_mbps: number | null;
}

export interface SimulationCompare {
  compatible?: boolean;
  comparison_reason?: string | null;
  simulation_id: string;
  baseline_simulation_id: string;
  scenario_id: string;
  baseline_scenario_id: string;
  network_id: string;
  simulation_metrics: SimulationMetricsSnapshot;
  baseline_metrics: SimulationMetricsSnapshot;
  deltas: SimulationMetricsSnapshot;
}
export interface ScenarioConfig {
  version: 1;
  seed: number;
  tick_ms: number;
  duration_ticks: number;
  links: { link_id: string; source: string; target: string; capacity_mbps: number; buffer_bytes: number; delay_ms: number; initial_queue_bytes: number }[];
  flows: { flow_id: string; source: string; target: string; path: string[]; demand_mbps: number[] }[];
  action_binding: null | { intent_id: string; plan_sha256: string; network_state_sha256: string };
  limits: { max_loss_pct: number; max_latency_ms: number; min_throughput_mbps: number };
}
export interface SimulationSummary {
  simulation_id: string;
  network_id: string;
  workspace_id: string;
  scenario_name: string;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface SimulationHistory {
  items: SimulationSummary[];
  total: number;
  page: number;
  page_size: number;
}

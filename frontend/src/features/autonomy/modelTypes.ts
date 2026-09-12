// backend/app/modules/autonomy/model_diagnostic_schemas.py (public ADR018 schemas only).
export interface ModelDiagnostic {
  diagnostic_id: string; network_id: string; workspace_id: string; actor_id: string; created_at: string;
  result: {
    model_id: string; checkpoint_id: string; history_reference: string;
    registry_sha256: string; policy_sha256: string; checkpoint_weights_sha256: string; source_sha256: string;
    history_sha256: string; input_sha256: string; contract_hash: string; spec_hash: string;
    action: 0 | 1; action_path: string[]; probabilities: [number, number]; value: number;
    inference_seconds: number; artifact_validation_and_inference_seconds: number; subprocess_seconds: number;
    evidence: Record<string, number | number[] | null>[];
    history_kind: "historical_measured_v4"; live: false; execution: "not_applied";
    safety_authorized: false; probabilities_are_safety_confidence: false;
    benchmark_status: "qualified_scoped_benchmark" | "not_qualified"; benchmark_scope: string;
    benchmark_limitations: string[]; benchmark_evidence_sha256: string;
  };
}
export interface ModelDiagnostics {
  network_id: string; workspace_id: string; status: "operator_registered" | "unavailable"; reasons: string[];
  model: null | {
    model_id: string; checkpoint_id: string; checkpoint_sha256: string; history_references: string[];
    status: "operator_registered"; benchmark_status: "qualified_scoped_benchmark" | "not_qualified";
    benchmark_scope: string; benchmark_limitations: string[];
  };
  diagnostics: ModelDiagnostic[];
  live_history_status: "unavailable"; safety_authorized: false; production_dispatch: false;
}

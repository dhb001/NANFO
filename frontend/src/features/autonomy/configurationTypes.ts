// backend/app/modules/autonomy/schemas.py: ConfigurationResponse / SetConfigurationRequest.
export interface OperationalSettings {
  max_observation_age_seconds: number; decision_interval_seconds: number;
  min_route_hold_seconds: number; max_changes_per_minute: number;
}
export interface TrainingSettings { reward_weights: Record<string, number> }
export interface ConfigurationRevision {
  revision: number; actor_id: string; reason: string; operational: OperationalSettings;
  training: TrainingSettings; content_sha256: string; created_at: string;
}
export interface Configuration {
  network_id: string; workspace_id: string; revision: number; control_revision: number;
  operational: OperationalSettings; requested_training: TrainingSettings; effective_training: TrainingSettings | null;
  training_status: "not_requested" | "retraining_required"; effective_training_status: "model_owned_unavailable";
  safety_merge: "stricter_than_calibrated_policy"; history: ConfigurationRevision[]; history_limit: number;
}
export interface ConfigurationUpdate {
  network_id: string; expected_revision: number; reason: string; operational: OperationalSettings; training: TrainingSettings;
}

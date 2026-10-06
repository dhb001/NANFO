// backend/app/modules/autonomy/schemas.py: ConfigurationResponse / SetConfigurationRequest.
export interface OperationalSettings {
  max_observation_age_seconds: number; decision_interval_seconds: number;
  min_route_hold_seconds: number; max_changes_per_minute: number;
  /** C17: autonomous dispatch needs calibrated confidence >= this (floor 0.95; operators may only tighten). */
  min_confidence: number;
  /** C17: honoured only in the enabled experimental lab (see allow_uncalibrated_confidence_honoured). */
  allow_uncalibrated_confidence: boolean;
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
  /** C17: whether operational.allow_uncalibrated_confidence can take effect in this deployment. */
  allow_uncalibrated_confidence_honoured: boolean;
}
export interface ConfigurationUpdate {
  network_id: string; expected_revision: number; reason: string; operational: OperationalSettings; training: TrainingSettings;
}

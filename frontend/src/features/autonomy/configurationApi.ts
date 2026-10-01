import { apiRequest } from "@/shared/lib/api";
import { ApiClientError } from "@/shared/lib/errors";
import { finite, hash, revision, timestamp, uuid } from "./contractChecks";
import type { Configuration, ConfigurationUpdate, OperationalSettings, TrainingSettings } from "./configurationTypes";

export const operationalBounds = {
  max_observation_age_seconds: [1, 30], decision_interval_seconds: [1, 3600],
  min_route_hold_seconds: [3, 3600], max_changes_per_minute: [1, 10],
} as const;
/** C17 confidence gate: the floor is the constitution's automatic-execution tier; operators may only tighten it. */
export const MIN_CONFIDENCE_BOUNDS = [0.95, 1] as const;
const CONFIDENCE_KEYS = ["min_confidence", "allow_uncalibrated_confidence"] as const;
export function validOperational(value: OperationalSettings, strict = false): boolean {
  // Every PUT carries the confidence gate explicitly: omitting it would silently reset a tightened threshold.
  return Boolean(value && (!strict || Object.keys(value).every((key) => Object.hasOwn(operationalBounds, key) || (CONFIDENCE_KEYS as readonly string[]).includes(key))) &&
    Object.entries(operationalBounds).every(([key, [min, max]]) => {
      const number = value[key as keyof typeof operationalBounds]; return Number.isInteger(number) && finite(number, min, max);
    }) && finite(value.min_confidence, MIN_CONFIDENCE_BOUNDS[0], MIN_CONFIDENCE_BOUNDS[1]) &&
    typeof value.allow_uncalibrated_confidence === "boolean");
}
export function validTraining(value: TrainingSettings): boolean {
  return Boolean(value && typeof value === "object" && Object.keys(value).every((key) => key === "reward_weights") &&
    value.reward_weights && typeof value.reward_weights === "object" && !Array.isArray(value.reward_weights) &&
    Object.keys(value.reward_weights).length <= 32 && Object.entries(value.reward_weights).every(([key, number]) => /^[a-z][a-z0-9_]{0,63}$/.test(key) && finite(number, -100, 100)));
}
export function validateConfiguration(data: Configuration, networkId: string, workspaceId: string) {
  if (data.network_id !== networkId || data.workspace_id !== workspaceId || !revision(data.revision) || !revision(data.control_revision) ||
      !validOperational(data.operational) || !validTraining(data.requested_training) || data.effective_training !== null ||
      data.effective_training_status !== "model_owned_unavailable" || !["not_requested", "retraining_required"].includes(data.training_status) ||
      data.safety_merge !== "stricter_than_calibrated_policy" || typeof data.allow_uncalibrated_confidence_honoured !== "boolean" ||
      !Number.isInteger(data.history_limit) || !finite(data.history_limit, 1, 100) ||
      !Array.isArray(data.history) || data.history.length > data.history_limit || !data.history.every((item) => item && revision(item.revision) &&
        item.revision <= data.revision && typeof item.actor_id === "string" && typeof item.reason === "string" && validOperational(item.operational) &&
        validTraining(item.training) && hash(item.content_sha256) && timestamp(item.created_at))) {
    throw new ApiClientError("Configuration is incompatible or outside the selected scope. No changes applied by this UI.", "CONFIGURATION_INVALID_RESPONSE");
  }
  return data;
}
export async function getConfiguration(token: string, networkId: string, workspaceId: string, signal?: AbortSignal) {
  const { data } = await apiRequest<Configuration>(`/api/v1/autonomy/configuration?${new URLSearchParams({ network_id: networkId })}`, { token, signal });
  return validateConfiguration(data, networkId, workspaceId);
}
export async function putConfiguration(token: string, workspaceId: string, input: ConfigurationUpdate) {
  if (!uuid(input.network_id) || !revision(input.expected_revision) || !input.reason.trim() || input.reason.length > 1000 ||
      !validOperational(input.operational, true) || !validTraining(input.training) ||
      Object.keys(input).some((key) => !["network_id", "expected_revision", "reason", "operational", "training"].includes(key))) {
    throw new Error("Unsupported configuration field or invalid bounded settings, reason or revision.");
  }
  const { data } = await apiRequest<Configuration>("/api/v1/autonomy/configuration", { token, method: "PUT", body: input }, false);
  return validateConfiguration(data, input.network_id, workspaceId);
}

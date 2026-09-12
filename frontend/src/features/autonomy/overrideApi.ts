import { apiRequest } from "@/shared/lib/api";
import { ApiClientError } from "@/shared/lib/errors";
import { finite, hash, revision, strings, timestamp, uuid } from "./contractChecks";
import type { OverrideCreate, OverrideList, TimedOverride } from "./overrideTypes";

const mode = (value: unknown) => ["monitor", "recommend", "autonomous"].includes(value as string);
function validateOverride(data: TimedOverride, networkId: string, workspaceId: string) {
  if (!data || data.network_id !== networkId || data.workspace_id !== workspaceId ||
      ![data.override_id, data.intent_id, data.execution_id, data.run_id].every(uuid) ||
      ![data.actor_id, data.reason].every((value) => typeof value === "string") ||
      !Number.isInteger(data.duration_seconds) || !finite(data.duration_seconds, 1, 3600) || !mode(data.return_mode) || !mode(data.prior_mode) ||
      ![data.prior_revision, data.hold_revision, data.restoration_attempts].every(revision) ||
      !(data.checkpoint_sha256 === null || hash(data.checkpoint_sha256)) || ![data.command_sha256, data.plan_hash, data.binding_digest].every(hash) ||
      ![data.configuration_verified_at, data.expires_at, data.created_at, data.updated_at].every(timestamp) ||
      ![data.prior_approval_expires_at, data.cancellation_requested_at, data.restored_at, data.return_requested_at, data.returned_at].every((value) => value === null || timestamp(value)) ||
      ![data.prior_approved_by_user_id, data.cancelled_by_user_id, data.return_requested_by_user_id, data.return_reason].every((value) => value === null || typeof value === "string") ||
      !(data.cancellation_id === null || uuid(data.cancellation_id)) || data.evidence_scope !== "historical_configuration_readback" ||
      !["holding", "restoring", "restored", "return_blocked", "returned"].includes(data.status) || !strings(data.reasons) ||
      !(data.verification === null || (typeof data.verification === "object" && !Array.isArray(data.verification)))) {
    throw new ApiClientError("Override response is incompatible or outside the selected scope. Restoration is not confirmed.", "OVERRIDE_INVALID_RESPONSE");
  }
  return data;
}
export async function getOverrides(token: string, networkId: string, workspaceId: string, signal?: AbortSignal) {
  const { data } = await apiRequest<OverrideList>(`/api/v1/autonomy/overrides?${new URLSearchParams({ network_id: networkId })}`, { token, signal });
  if (data.network_id !== networkId || !revision(data.control_revision) || !finite(data.history_limit, 1, 100) ||
      !Number.isInteger(data.history_limit) || !Array.isArray(data.overrides) || data.overrides.length > data.history_limit) throw new Error("Override history is incompatible with this scope.");
  data.overrides.forEach((item) => validateOverride(item, networkId, workspaceId));
  return data;
}
export async function createOverride(token: string, workspaceId: string, input: OverrideCreate) {
  if (![input.network_id, input.intent_id, input.execution_id].every(uuid) || !revision(input.expected_revision) ||
      !input.reason.trim() || input.reason.length > 1000 || !Number.isInteger(input.duration_seconds) || !finite(input.duration_seconds, 1, 3600) || !mode(input.return_mode)) throw new Error("Valid UUIDs, revision, reason and duration from 1 to 3600 seconds are required.");
  const { data } = await apiRequest<TimedOverride>("/api/v1/autonomy/overrides", { token, method: "POST", body: input }, false);
  validateOverride(data, input.network_id, workspaceId);
  if (data.intent_id !== input.intent_id || data.execution_id !== input.execution_id) throw new Error("Enrollment response belongs to a different execution.");
  return data;
}
export async function actOnOverride(token: string, networkId: string, workspaceId: string, id: string,
  action: "cancel" | "return", input?: { expected_revision: number; reason: string }) {
  if (!uuid(id) || (action === "return" && (!input || !revision(input.expected_revision) || !input.reason.trim() || input.reason.length > 1000))) throw new Error("A scoped override and fresh explicit return reason/revision are required.");
  const { data } = await apiRequest<TimedOverride>(`/api/v1/autonomy/overrides/${id}/${action}`, { token, method: "POST", body: action === "return" ? input : undefined }, false);
  validateOverride(data, networkId, workspaceId);
  if (data.override_id !== id) throw new Error("Override response identity differs from the requested override.");
  return data;
}

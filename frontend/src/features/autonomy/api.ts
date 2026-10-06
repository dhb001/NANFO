import { apiRequest } from "@/shared/lib/api";
import { ApiClientError } from "@/shared/lib/errors";
import type { ApiMeta } from "@/shared/types/api";
import type {
  AutonomyConfidence, AutonomyDecision, AutonomyObservation, AutonomyPendingApproval, AutonomyStatus, AutonomyUpdate, AutonomyUpdateResult,
  SafetyCertificate, SafetyBinding,
} from "./types";

/** PUT /autonomy meta (C25): the request was recorded for a second approver, not applied. */
interface AutonomyModeMeta extends ApiMeta {
  pending_approval?: boolean;
  pending_approval_expires_at?: string | null;
  pending_requested_by_user_id?: string | null;
}

const strings = (value: unknown): value is string[] => Array.isArray(value) && value.every((item) => typeof item === "string");
const nullableString = (value: unknown) => value === null || typeof value === "string";
const sha256 = (value: unknown) => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
const unixTime = (value: unknown) => typeof value === "number" && Number.isFinite(value) && Math.abs(value) <= 8_640_000_000_000;

function validCertificate(value: SafetyCertificate | null | undefined, networkId: string): boolean {
  if (value == null) return true;
  return value.model === "bounded-fluid-v1" && value.conditional === true && value.network_id === networkId &&
    sha256(value.input_sha256) && typeof value.model_checks_passed === "boolean" &&
    [value.calibration_id, value.provider_id, value.policy_version, value.run_id, value.snapshot_id, value.action_id].every((item) => typeof item === "string") &&
    [value.observed_at_unix_seconds, value.horizon_end_unix_seconds, value.expires_at_unix_seconds].every(unixTime) &&
    Number.isFinite(value.dt_seconds) && Number.isFinite(value.actuation_delay_upper_seconds) &&
    Boolean(value.drift && [value.drift.v_before_bytes_squared, value.drift.v_next_upper_bytes_squared,
      value.drift.upper_bytes_squared, value.drift.budget_bytes_squared].every(Number.isFinite)) &&
    Boolean(value.envelope && Number.isFinite(value.envelope.threshold_bytes) && value.envelope.q_next_upper_bytes &&
      typeof value.envelope.q_next_upper_bytes === "object" && !Array.isArray(value.envelope.q_next_upper_bytes) &&
      Object.values(value.envelope.q_next_upper_bytes).every(Number.isFinite)) &&
    Array.isArray(value.routes) && value.routes.every((route) => route && typeof route.demand_id === "string" && typeof route.route_id === "string");
}

function validBinding(value: SafetyBinding | null | undefined, workspaceId: string): boolean {
  return value == null || (value.workspace_id === workspaceId && unixTime(value.evaluated_at_unix_seconds) &&
    [value.observation_sha256, value.proposal_sha256, value.calibration_sha256, value.selected_action_sha256].every(sha256));
}

/** C17: honest calibration — a calibrated value always names its calibration, an uncalibrated one never does. */
export function validConfidence(value: AutonomyConfidence | null | undefined): boolean {
  if (value == null) return true;
  const calibrationId = value.calibration_id ?? null;
  return typeof value.value === "number" && Number.isFinite(value.value) && value.value >= 0 && value.value <= 1 &&
    typeof value.method === "string" && value.method.length > 0 && typeof value.calibrated === "boolean" &&
    (calibrationId === null || typeof calibrationId === "string") && value.calibrated === (calibrationId !== null);
}

function validPendingApproval(value: AutonomyPendingApproval | null | undefined): boolean {
  return value == null || Boolean(typeof value.requested_by_user_id === "string" && ["monitor", "recommend", "autonomous"].includes(value.mode) &&
    Number.isSafeInteger(value.expected_revision) && nullableString(value.checkpoint_sha256) && nullableString(value.approval_expires_at) &&
    typeof value.requested_at === "string" && typeof value.expires_at === "string");
}

function validObservation(value: AutonomyObservation | null, networkId: string, workspaceId: string): boolean {
  return value === null || Boolean(value && value.network_id === networkId && value.workspace_id === workspaceId &&
    typeof value.provider_id === "string" && typeof value.contract === "string" &&
    typeof value.fresh === "boolean" && typeof value.compatible === "boolean" &&
    nullableString(value.observed_at) && typeof value.collected_at === "string" &&
    (value.age_seconds === null || Number.isFinite(value.age_seconds)) && strings(value.reasons) && strings(value.evidence) &&
    Array.isArray(value.samples) && value.samples.length <= 100);
}

function validDecision(value: AutonomyDecision | null, networkId: string, workspaceId: string): boolean {
  return Boolean(value && value.network_id === networkId && value.workspace_id === workspaceId &&
    typeof value.decision_id === "string" && typeof value.actor_id === "string" &&
    ["monitor", "recommend", "autonomous"].includes(value.mode) && Number.isInteger(value.control_revision) &&
    ["observing", "observed", "blocked", "recommended", "accepted", "verified", "uncertain", "cancelled", "failed", "control_changed", "stopped"].includes(value.status) &&
    strings(value.reasons) && strings(value.evidence) && nullableString(value.checkpoint_sha256) && nullableString(value.execution_id) &&
    validConfidence(value.confidence) && (value.proposal === null || validConfidence(value.proposal?.confidence)) &&
    typeof value.created_at === "string" && typeof value.updated_at === "string" && validObservation(value.observation, networkId, workspaceId) &&
    (value.safety === null || (value.safety && typeof value.safety.admissible === "boolean" && typeof value.safety.model_version === "string" &&
      strings(value.safety.reasons) && strings(value.safety.evidence) && validCertificate(value.safety.certificate, networkId) && validBinding(value.safety.binding, workspaceId))) &&
    (value.verification === null || (value.verification && value.verification.execution_id === value.execution_id &&
      ["pending", "verified", "cancelled", "failed", "uncertain"].includes(value.verification.status) &&
      typeof value.verification.safe_to_release === "boolean" && strings(value.verification.reasons) && strings(value.verification.evidence))));
}

async function requestStatus(token: string, networkId: string, workspaceId: string, options: { method?: "PUT" | "POST"; body?: unknown; signal?: AbortSignal | undefined } = {}) {
  return (await requestEnvelope(token, networkId, workspaceId, options)).data;
}

async function requestEnvelope(token: string, networkId: string, workspaceId: string, options: { method?: "PUT" | "POST"; body?: unknown; signal?: AbortSignal | undefined } = {}) {
  const path = options.method === "POST" ? "/api/v1/autonomy/stop"
    : options.method === "PUT" ? "/api/v1/autonomy"
      : `/api/v1/autonomy?${new URLSearchParams({ network_id: networkId })}`;
  const response = await apiRequest<AutonomyStatus, AutonomyModeMeta>(path, { token, ...options });
  const data = response.data;
  if (data.network_id !== networkId || data.workspace_id !== workspaceId) {
    throw new ApiClientError("Autonomy response does not match the selected scope.", "AUTONOMY_SCOPE_MISMATCH");
  }
  if (!["monitor", "recommend", "autonomous"].includes(data.mode) || typeof data.ready !== "boolean" ||
      !["monitoring", "ready", "blocked", "stopped", "executing", "uncertain"].includes(data.status) ||
      !["none", "requested", "verified", "uncertain"].includes(data.cancellation_status) ||
      typeof data.emergency_stopped !== "boolean" || data.online_learning !== false || data.production_dispatch !== false ||
      !strings(data.blocked_reasons) || !Number.isSafeInteger(data.revision) || data.revision < 0 ||
      !Number.isInteger(data.history_limit) || data.history_limit < 1 || data.history_limit > 100 ||
      ![data.checkpoint_sha256, data.approval_expires_at, data.approved_by_user_id, data.active_execution_id,
        data.stopped_at, data.stopped_by_user_id, data.updated_at].every(nullableString) ||
      !Array.isArray(data.decisions) || data.decisions.length > 100 ||
      !["observer", "qualification", "inference", "safety", "executor"].every((key) => {
        const provider = data.providers?.[key as keyof AutonomyStatus["providers"]];
        return provider && typeof provider.provider_id === "string" &&
          ["ready", "unavailable", "incompatible", "uncalibrated"].includes(provider.status) &&
          Array.isArray(provider.reasons) && provider.reasons.every((reason) => typeof reason === "string");
      }) || data.decisions.some((decision) => !validDecision(decision, networkId, workspaceId)) ||
      (data.last_decision !== null && !validDecision(data.last_decision, networkId, workspaceId)) ||
      !validObservation(data.last_observation, networkId, workspaceId) || !validPendingApproval(data.pending_approval)) {
    throw new ApiClientError("Autonomy status is incomplete or incompatible. Controls remain unavailable.", "AUTONOMY_INVALID_STATUS");
  }
  return { data, meta: response.meta };
}

export function getAutonomy(token: string, networkId: string, workspaceId: string, signal?: AbortSignal) {
  return requestStatus(token, networkId, workspaceId, { signal });
}

export async function updateAutonomy(token: string, workspaceId: string, input: AutonomyUpdate): Promise<AutonomyUpdateResult> {
  if (!Number.isSafeInteger(input.expected_revision) || input.expected_revision < 0) {
    throw new ApiClientError("A confirmed control revision is required.", "AUTONOMY_INVALID_REVISION");
  }
  const { data, meta } = await requestEnvelope(token, input.network_id, workspaceId, { method: "PUT", body: input });
  return { status: data, pendingApproval: meta.pending_approval === true, pendingApprovalExpiresAt: meta.pending_approval_expires_at ?? null };
}

/** Bounded retries for 503 AUTONOMY_STOP_BUSY (the latch lock was contended); STOP is idempotent. */
export const STOP_BUSY_ATTEMPTS = 3;

export async function stopAutonomy(token: string, networkId: string, workspaceId: string,
  wait: (ms: number) => Promise<void> = (ms) => new Promise((resolve) => setTimeout(resolve, ms))) {
  for (let attempt = 1; ; attempt++) {
    try {
      return await requestStatus(token, networkId, workspaceId, { method: "POST", body: { network_id: networkId } });
    } catch (error) {
      if (!(error instanceof ApiClientError) || error.code !== "AUTONOMY_STOP_BUSY" || attempt >= STOP_BUSY_ATTEMPTS) throw error;
      await wait(Math.min(Math.max(error.retryAfterMs ?? 1_000, 100), 5_000));
    }
  }
}

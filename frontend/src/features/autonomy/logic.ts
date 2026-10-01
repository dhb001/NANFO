import { ApiClientError, describeApiError } from "@/shared/lib/errors";
import type { AutonomyConfidence, AutonomyMode, AutonomyUpdate } from "./types";

/**
 * Honest confidence text (C17): the value is always shown with its method, and anything not
 * calibrated says so, because only calibrated confidence can authorize autonomous dispatch.
 */
export function describeConfidence(confidence: AutonomyConfidence | null | undefined): { text: string; calibrated: boolean } {
  if (!confidence) return { text: "Confidence not reported (no proposal, or recorded before typed confidence).", calibrated: false };
  const value = `${confidence.value.toFixed(3)} (${confidence.method})`;
  return confidence.calibrated
    ? { text: `Confidence ${value}, calibrated by ${confidence.calibration_id ?? "an unnamed calibration"}.`, calibrated: true }
    : { text: `Confidence ${value}, UNCALIBRATED: a raw model output that cannot authorize autonomous dispatch.`, calibrated: false };
}

// C25 governance refusals (backend/app/modules/autonomy/service.py).
const GOVERNANCE_MESSAGES: Record<string, string> = {
  AUTONOMY_DISTINCT_APPROVER_REQUIRED: "You requested this autonomous switch; a different authorized user must confirm the identical request.",
  AUTONOMY_STOP_CLEAR_REQUIRES_ADMIN: "Only an organization Admin can clear the emergency stop. The stop remains latched.",
  AUTONOMY_STOP_BUSY: "The emergency-stop latch stayed busy after automatic retries. Press Emergency stop again now; do not assume execution stopped.",
};

export function describeAutonomyError(error: unknown): string {
  if (error instanceof ApiClientError && Object.hasOwn(GOVERNANCE_MESSAGES, error.code)) {
    return `${GOVERNANCE_MESSAGES[error.code]}${error.requestId ? ` Reference: ${error.requestId}.` : ""}`;
  }
  return describeApiError(error);
}

export function buildAutonomyUpdate(networkId: string, mode: AutonomyMode, hash: string, expiry: string, expectedRevision: number, now = Date.now()): AutonomyUpdate {
  if (!Number.isSafeInteger(expectedRevision) || expectedRevision < 0) {
    throw new Error("A confirmed nonnegative control revision is required. Refresh status before submitting.");
  }
  const checkpoint = hash.trim().toLowerCase() || null;
  if (checkpoint !== null && !/^[a-f0-9]{64}$/.test(checkpoint)) {
    throw new Error("Checkpoint must be exactly 64 hexadecimal SHA-256 characters, not a path.");
  }
  const expiresAt = mode === "autonomous" && expiry ? Date.parse(expiry) : NaN;
  if (mode === "autonomous" && expiry && (!Number.isFinite(expiresAt) || expiresAt <= now)) {
    throw new Error("Approval expiry must be a valid future date and time.");
  }
  if (mode === "autonomous" && (!checkpoint || !expiry)) {
    throw new Error("Autonomous approval requires an exact checkpoint SHA-256 and a future expiry.");
  }
  if (mode === "autonomous" && expiresAt > now + 3_600_000) {
    throw new Error("Autonomous approval must expire within one hour (backend maximum).");
  }
  return {
    network_id: networkId,
    expected_revision: expectedRevision,
    mode,
    checkpoint_sha256: checkpoint,
    approval_expires_at: mode === "autonomous" ? new Date(expiresAt).toISOString() : null,
  };
}

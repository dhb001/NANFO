import type { AutonomyMode, AutonomyUpdate } from "./types";

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

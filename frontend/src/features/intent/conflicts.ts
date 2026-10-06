import { ApiClientError } from "@/shared/lib/errors";

/** What the page does after a definitive intent conflict (the request was refused; nothing ran). */
export interface IntentConflictGuidance {
  code: string;
  title: string;
  description: string;
  /** Re-read the intent detail (its binding, key or status changed). */
  refetchDetail: boolean;
  /** Clear the operator's local approval so the current identity is approved again. */
  revokeApproval: boolean;
}

// Backend 409 codes (docs: WAVE1 BE-Workflows handoff; intent/execution.py, intent/service.py).
const GUIDANCE: Record<string, Omit<IntentConflictGuidance, "code">> = {
  IDEMPOTENCY_KEY_REUSED: {
    title: "Request key already used",
    description: "That validation key already identifies a different submission in this workspace. A new key was generated; validate again.",
    refetchDetail: false, revokeApproval: false,
  },
  INTENT_IDEMPOTENCY_CONFLICT: {
    title: "Execution identity conflict",
    description: "Execute and cancel must reuse this intent's stored key. The detail was re-read; retry with the current identity.",
    refetchDetail: true, revokeApproval: true,
  },
  APPROVAL_BINDING_MISMATCH: {
    title: "Lab identity changed since approval",
    description: "The plan, binding or lab run no longer matches what you approved. The detail was re-read; review and approve the current lab identity again.",
    refetchDetail: true, revokeApproval: true,
  },
  DISTINCT_APPROVER_REQUIRED: {
    title: "A different approver is required",
    description: "Manual lab execution must be approved by a user other than the intent's requester (four-eyes rule).",
    refetchDetail: false, revokeApproval: true,
  },
  SIMULATION_REQUIRED: {
    title: "Simulation required first",
    description: "High-impact lab actions need a completed, passing simulation of this network bound to the intent's simulation action binding. Reference its UUID and retry.",
    refetchDetail: false, revokeApproval: true,
  },
  SIMULATION_POLICY_VIOLATION: {
    title: "Simulation limits weaker than policy",
    description: "The referenced simulation's limits are weaker than the server policy floors, so it can never authorize this execution. Run a new simulation within the floors.",
    refetchDetail: false, revokeApproval: true,
  },
  SIMULATION_EVIDENCE_REJECTED: {
    title: "Simulation evidence rejected",
    description: "The referenced simulation is missing, belongs to another network or plan, failed its checks, or its evidence expired. Reference a current passing simulation.",
    refetchDetail: false, revokeApproval: true,
  },
  INTENT_ALREADY_EXECUTING: {
    title: "Execution already started",
    description: "Another request already started this intent. The detail was re-read; follow its reconciliation instead of retrying.",
    refetchDetail: true, revokeApproval: true,
  },
};

export function intentConflictGuidance(error: unknown): IntentConflictGuidance | null {
  if (!(error instanceof ApiClientError) || error.status !== 409) return null;
  const guidance = GUIDANCE[error.code];
  return guidance ? { code: error.code, ...guidance } : null;
}

/**
 * A lost response, timeout, proxy failure or server error: the request may have been
 * applied. Retry with the same identity instead of minting a new one.
 */
export function isUnknownOutcome(error: unknown): boolean {
  if (!(error instanceof ApiClientError)) return true;
  // Refused locally before anything was sent.
  if (error.code === "API_NO_SESSION" || error.code === "API_AUTHORITY_CHANGED") return false;
  if (error.code === "API_TIMEOUT" || error.code === "API_INVALID_RESPONSE" || error.code === "API_EMPTY_RESPONSE") return true;
  return error.status === undefined || error.status === 0 || error.status >= 500;
}

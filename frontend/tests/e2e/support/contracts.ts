// Mock-backend fixtures typed with the generated backend OpenAPI schemas (ADR-028 R02 lesson):
// `npm run typecheck` fails when a mocked response drifts from the real contract.
import type { components } from "../../../src/shared/types/generated/openapi";

export type Schema<Name extends keyof components["schemas"]> = components["schemas"][Name];

const AT = "2026-09-09T12:00:00Z";
const REQUESTER = "00000000-0000-0000-0000-000000000124";

export function okEnvelope<T>(data: T, meta: Record<string, unknown> = {}) {
  return { success: true as const, data, meta: { request_id: "e2e", timestamp: AT, execution_mode: "emulation", ...meta }, errors: null };
}

export function errorEnvelope(code: string, message: string, meta: Record<string, unknown> = {}) {
  return { success: false as const, data: null, meta: { request_id: "e2e-error", timestamp: AT, ...meta }, errors: { code, message } };
}

export const lowConfidence: Schema<"IntentConfidenceState"> = { score: 0, band: "below_60", approval_required: true };

type Required<T, K extends keyof T> = Partial<T> & Pick<T, K>;

export function intentDetail(fields: Required<Schema<"IntentDetailResponse">, "intent_id" | "workspace_id">): Schema<"IntentDetailResponse"> {
  return {
    network_id: null, status: "validated", intent_kind: "reroute_path", intent_payload: {}, validation_result: {},
    execution_provenance: {}, explainability: {}, confidence: lowConfidence, idempotency_key: null, queue_status: "queued",
    stream_entry_id: null, warning: null, correlation_id: "00000000-0000-0000-0000-00000000c0de", requested_by_user_id: REQUESTER,
    requested_at: AT, created_at: AT, updated_at: AT, approval_binding: null, simulation_action_binding: null,
    ...fields,
  };
}

export function validateResponse(fields: Required<Schema<"ValidateIntentResponse">, "intent_id" | "workspace_id">): Schema<"ValidateIntentResponse"> {
  return {
    network_id: null, status: "validated", intent_kind: "reroute_path",
    validation: {
      is_valid: true, reasons: [], required_checks: [], capability_match: "baseline_schema_match", dependency_analysis: "not_performed",
      simulation_required: true, policy_reference: "ADR-008", validated_at: AT, validation_kind: "baseline_schema_only", model_evidence: "unavailable",
    },
    explainability: { summary: "Intent passed baseline UNIL validation checks.", evidence: [], alternatives_considered: ["manual_review"], policy_reference: "ADR-008" },
    confidence: lowConfidence, idempotency_key: null, correlation_id: "00000000-0000-0000-0000-00000000c0de", requested_at: AT,
    queue_status: "queued", stream_entry_id: null, warning: null, idempotent_replay: false, approval_binding: null, simulation_action_binding: null,
    ...fields,
  };
}

export function executeResponse(fields: Required<Schema<"ExecuteIntentResponse">, "intent_id" | "workspace_id">): Schema<"ExecuteIntentResponse"> {
  return {
    network_id: null, status: "execution_started", intent_kind: "reroute_path", queue_status: "outbox_pending", stream_entry_id: null,
    warning: null, validation_result: {}, execution_provenance: {}, explainability: {}, confidence: lowConfidence, idempotency_key: null,
    correlation_id: "00000000-0000-0000-0000-00000000c0de", requested_by_user_id: REQUESTER, requested_at: AT, updated_at: AT,
    idempotent_replay: false, approval_binding: null,
    ...fields,
  };
}

export const labApprovalBinding: Schema<"ApprovalBinding"> = {
  plan_hash: "c".repeat(64), binding_digest: "d".repeat(64), run_id: "00000000-0000-0000-0000-0000000000aa",
};

// Compile-time drift guards for the long-lived mock records in ./session (ADR-028 R02 lesson):
// a mock must be a valid backend response (assignable) and must not invent fields.
import type { MockAlertRecord, MockDevice, MockNetwork, MockPluginRecord, MockReportArtifactRef, MockReportRecord } from "./session";

type Ok<Check extends true> = Check;
type NoInvented<Mock, Backend> = [Exclude<keyof Mock, keyof Backend>] extends [never] ? true : ["Invented mock fields:", Exclude<keyof Mock, keyof Backend>];
type ValidResponse<Mock, Backend> = [Mock] extends [Backend] ? true : ["Mock is not a valid backend response"];

export type MockContractGuards = [
  Ok<NoInvented<MockNetwork, Schema<"NetworkResponse">>>, Ok<ValidResponse<MockNetwork, Schema<"NetworkResponse">>>,
  Ok<NoInvented<MockDevice, Schema<"DeviceResponse">>>, Ok<ValidResponse<MockDevice, Schema<"DeviceResponse">>>,
  Ok<NoInvented<MockAlertRecord, Schema<"AlertRecordResponse">>>, Ok<ValidResponse<MockAlertRecord, Schema<"AlertRecordResponse">>>,
  Ok<NoInvented<MockPluginRecord, Schema<"PluginRecordResponse">>>, Ok<ValidResponse<MockPluginRecord, Schema<"PluginRecordResponse">>>,
  Ok<NoInvented<MockReportArtifactRef, Schema<"ReportArtifactRef">>>, Ok<ValidResponse<MockReportArtifactRef, Schema<"ReportArtifactRef">>>,
  Ok<NoInvented<MockReportRecord, Schema<"ReportRecordResponse">>>, Ok<ValidResponse<MockReportRecord, Schema<"ReportRecordResponse">>>,
];

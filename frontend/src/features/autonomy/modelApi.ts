import { apiRequest } from "@/shared/lib/api";
import { ApiClientError } from "@/shared/lib/errors";
import { finite, hash, registryId, strings, timestamp, uuid } from "./contractChecks";
import type { ModelDiagnostic, ModelDiagnostics } from "./modelTypes";

function validRecord(record: ModelDiagnostic, networkId: string, workspaceId: string) {
  const r = record?.result;
  return record && record.network_id === networkId && record.workspace_id === workspaceId && uuid(record.diagnostic_id) &&
    typeof record.actor_id === "string" && timestamp(record.created_at) && r &&
    [r.model_id, r.checkpoint_id, r.history_reference].every(registryId) &&
    [r.registry_sha256, r.policy_sha256, r.checkpoint_weights_sha256, r.source_sha256, r.history_sha256, r.input_sha256,
      r.contract_hash, r.spec_hash, r.benchmark_evidence_sha256].every(hash) &&
    (r.action === 0 || r.action === 1) && strings(r.action_path) && r.action_path.length > 0 && r.action_path.length <= 10 &&
    Array.isArray(r.probabilities) && r.probabilities.length === 2 && r.probabilities.every((p) => finite(p, 0, 1)) &&
    Math.abs(r.probabilities[0] + r.probabilities[1] - 1) <= 1e-6 && r.probabilities[r.action] === Math.max(...r.probabilities) &&
    Number.isFinite(r.value) && finite(r.inference_seconds, 0, 30) && finite(r.artifact_validation_and_inference_seconds, 0, 30) && finite(r.subprocess_seconds, 0, 35) &&
    r.history_kind === "historical_measured_v4" && r.live === false && r.execution === "not_applied" &&
    r.safety_authorized === false && r.probabilities_are_safety_confidence === false &&
    ["qualified_scoped_benchmark", "not_qualified"].includes(r.benchmark_status) && typeof r.benchmark_scope === "string" && strings(r.benchmark_limitations) &&
    Array.isArray(r.evidence) && r.evidence.length >= 1 && r.evidence.length <= 3 && r.evidence.every((item) => item && typeof item === "object" &&
      Object.values(item).every((value) => value === null || Number.isFinite(value) || (Array.isArray(value) && value.every(Number.isFinite))));
}

export async function getModelDiagnostics(token: string, networkId: string, workspaceId: string, signal?: AbortSignal) {
  const { data } = await apiRequest<ModelDiagnostics>(`/api/v1/autonomy/model?${new URLSearchParams({ network_id: networkId })}`, { token, signal });
  const model = data.model;
  if (data.network_id !== networkId || data.workspace_id !== workspaceId || !["operator_registered", "unavailable"].includes(data.status) ||
      !strings(data.reasons) || data.live_history_status !== "unavailable" || data.safety_authorized !== false || data.production_dispatch !== false ||
      !(model === null || (model && registryId(model.model_id) && registryId(model.checkpoint_id) && hash(model.checkpoint_sha256) &&
        strings(model.history_references) && model.history_references.length <= 100 && model.history_references.every(registryId) &&
        model.status === "operator_registered" && ["qualified_scoped_benchmark", "not_qualified"].includes(model.benchmark_status) &&
        typeof model.benchmark_scope === "string" && strings(model.benchmark_limitations))) ||
      !Array.isArray(data.diagnostics) || data.diagnostics.length > 100 || !data.diagnostics.every((record) => validRecord(record, networkId, workspaceId))) {
    throw new ApiClientError("Model diagnostics are incompatible or outside the selected scope.", "MODEL_INVALID_RESPONSE");
  }
  return data;
}

export async function diagnoseModel(token: string, networkId: string, workspaceId: string, historyReference: string) {
  if (!uuid(networkId) || !registryId(historyReference)) throw new Error("Select an allowlisted history reference, not a filesystem path.");
  const { data } = await apiRequest<ModelDiagnostic>("/api/v1/autonomy/model/diagnose", {
    token, method: "POST", body: { network_id: networkId, history_reference: historyReference },
  }, false);
  if (!validRecord(data, networkId, workspaceId) || data.result.history_reference !== historyReference) {
    throw new ApiClientError("Inference result is incompatible or outside the requested scope/history.", "MODEL_INVALID_RESPONSE");
  }
  return data;
}

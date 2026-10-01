import type { IntentDetailResult } from "@/shared/types/intent";

function text(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

/** Discloses what the backend validation actually covered (ADR-028: schema-only unless model-backed). */
export function ValidationDisclosure({ detail }: { detail: IntentDetailResult }) {
  const validation = detail.validation_result;
  const kind = text(validation.validation_kind);
  const modelEvidence = text(validation.model_evidence);
  return <div role="note" aria-label="Validation coverage">
    {kind === "manual_lab_plan"
      ? <p>Validated against the trusted manual lab plan: observed paths, lab binding and capabilities were checked by the server. This is not a model prediction of traffic effects.</p>
      : kind === null || kind === "baseline_schema_only"
        ? <p><strong>Schema-only validation.</strong> The backend checked the intent's structure only; no model, dependency or capability evaluation backs it (model evidence: {modelEvidence ?? "unavailable"}).</p>
        : <p>Validation kind: {kind} (model evidence: {modelEvidence ?? "not reported"}).</p>}
    {validation.simulation_required === true
      ? <p>Simulation required before execution: reference a completed, passing simulation of this network bound to the simulation action binding below.</p>
      : null}
  </div>;
}

/** The exact lab identity Execute sends (C3) and the binding a pre-execution simulation must carry (C18). */
export function ApprovalBindingSummary({ detail, labAction }: { detail: IntentDetailResult; labAction: boolean }) {
  if (!labAction) return null;
  const binding = detail.approval_binding;
  const simulationBinding = detail.simulation_action_binding;
  return <div aria-label="Approval binding" style={{ overflowWrap: "anywhere" }}>
    {binding
      ? <>
        <p>Approval binding (sent with Execute; approving means approving exactly this lab identity):</p>
        <div className="mono">plan_hash: {binding.plan_hash}</div>
        <div className="mono">binding_digest: {binding.binding_digest}</div>
        <div className="mono">run_id: {binding.run_id}</div>
      </>
      : <p role="status">No approval binding recorded. The server refuses lab execution until the intent is validated against the current lab.</p>}
    {simulationBinding
      ? <details>
        <summary>Simulation action binding (copy verbatim into scenario_config.action_binding)</summary>
        <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{JSON.stringify(simulationBinding, null, 2)}</pre>
      </details>
      : null}
  </div>;
}

import type { IntentDetailResult } from "@/shared/types/intent";
import { mapExecutionDiagnostics } from "./logic";

export function PathEvidencePanel({ detail }: { detail: IntentDetailResult }) {
  const provenance = detail.execution_provenance;
  const raw = provenance.approved_plan;
  const plan = raw && typeof raw === "object" && !Array.isArray(raw) ? raw as Record<string, unknown> : null;
  const paths = plan && Array.isArray(plan.paths) && plan.paths.length <= 2 && plan.paths.every((path) =>
    Array.isArray(path) && path.length > 0 && path.length <= 64 && path.every((step) => typeof step === "string" && /^[a-z][a-z0-9]{0,31}$/.test(step))) ? plan.paths as string[][] : null;
  const diagnostics = mapExecutionDiagnostics(detail);
  const hash = typeof provenance.plan_hash === "string" && /^[a-f0-9]{64}$/.test(provenance.plan_hash) ? provenance.plan_hash : null;
  const verified = Boolean(plan && paths && hash && diagnostics.verificationStatus === "readback verified" &&
    typeof plan.operation === "string" && ["reroute", "multipath", "shape", "police", "restore"].includes(plan.operation) &&
    typeof plan.source_host === "string" && typeof plan.destination_host === "string" &&
    detail.status === "execution_completed" && provenance.phase === "completed" && provenance.uncertain !== true &&
    provenance.cancel_requested !== true &&
    diagnostics.rollbackStatus !== "verified" && diagnostics.rollbackStatus !== "unverified" && diagnostics.rollbackStatus !== "failed" && !diagnostics.rollbackAttempted);
  return <section aria-label="Configuration path evidence" style={{ overflowWrap: "anywhere" }}>
    <h3>{verified ? "Configuration-verified path evidence" : "Configuration path evidence unavailable"}</h3>
    <p>Observed packet traversal unavailable. Configuration readback and reachability are not proof of the path taken by packets or of performance improvement.</p>
    {!plan || !paths ? <p>Persisted approved plan unavailable or unsupported. Paths are not reconstructed from editable intent inputs.</p> : <>
      <p>Operation: {typeof plan.operation === "string" ? plan.operation : "Unavailable"}. Scope: {typeof plan.source_host === "string" ? plan.source_host : "Unavailable"} to {typeof plan.destination_host === "string" ? plan.destination_host : "Unavailable"}.</p>
      {!verified && <p>Approved configuration only; successful current readback is not established, or rollback/uncertainty supersedes it.</p>}
      {paths.length === 0 ? <p>This approved operation contains no route steps.</p> : paths.map((path, index) => <div key={index}>
        <strong>Approved route {index + 1}</strong>
        <ol>{path.map((step, stepIndex) => <li key={`${stepIndex}-${step}`}>{step}</li>)}</ol>
      </div>)}
      <p>Route steps retain lab hostnames. Canonical device mapping is unavailable; ambiguous names are not guessed.</p>
    </>}
    <div className="mono">Approved plan SHA-256: {hash ?? "Unavailable"}</div>
    <div className="mono">Readback evidence SHA-256: {diagnostics.readbackSha256 ?? "Unavailable"}</div>
    <p>Readback scope: {diagnostics.completionScope ?? "Unavailable"}. This is recorded execution evidence, not continuous live verification.</p>
    <p>Model status and inference decision evidence are unavailable through this contract. Manual approval is not learned confidence.</p>
  </section>;
}

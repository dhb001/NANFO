import { useEffect, useState } from "react";
import type { SimulationDetail } from "@/shared/types/simulation";
import { modeledMetrics, modeledOutput } from "./modeledOutput";

export function ModeledEvidence({ detail }: { detail: SimulationDetail }) {
  const output = modeledOutput(detail);
  const [showOutput, setShowOutput] = useState(false);
  const [now, setNow] = useState(Date.now);
  const expiry = detail.evidence_expires_at ? Date.parse(detail.evidence_expires_at) : NaN;
  useEffect(() => {
    if (!Number.isFinite(expiry) || expiry <= Date.now()) return;
    const timer = window.setTimeout(() => setNow(Date.now()), Math.min(expiry - Date.now() + 10, 2147483647));
    return () => window.clearTimeout(timer);
  }, [expiry]);
  return <section aria-label="Modeled simulation evidence" style={{ minWidth: 0, overflowWrap: "anywhere" }}>
    <h3>Configured model evidence</h3>
    <p>Model computation completion is separate from a risk-gate pass. Neither grants physical production authorization or global safety proof.</p>
    {detail.progress && <p>Persisted progress: tick {detail.progress.tick} / {detail.progress.duration_ticks}.</p>}
    {!output ? <p>Modeled output unavailable: legacy or unversioned results are not verified model evidence.</p> : <>
      <p>Model: {String(output.model_version)} | Modeled elapsed time: {typeof output.elapsed_ms === "number" ? `${output.elapsed_ms} ms` : "Unavailable"}</p>
      <dl>{Object.entries(modeledMetrics).map(([key, metric]) => <div key={key}><dt>Modeled {metric.label.toLowerCase()}</dt><dd>{typeof output[key] === "number" && Number.isFinite(output[key]) ? `${output[key]} ${metric.unit}` : "Unavailable"}</dd></div>)}</dl>
      <p>Latency definition: {typeof output.latency_definition === "string" ? output.latency_definition : "Unavailable"}</p>
      <p>Finite-buffer fluid approximation with proportional shared service, mixed queues and tick-rounded propagation. No packet-level simulation, measured RTT or calibrated safety bound is implied. Goodput is delivered bytes per modeled elapsed time; loss is dropped/offered bytes. Undelivered queued/inflight traffic is not counted as delivered.</p>
      <div>{["input_sha256", "checkpoint_sha256", "output_sha256", "workload_sha256"].map((key) => <div key={key} className="mono">{key}: {String(output[key])}</div>)}</div>
      <details onToggle={(event) => setShowOutput(event.currentTarget.open)}><summary>Modeled output, objective checks and link/flow histories</summary>{showOutput && <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", maxHeight: 360, overflow: "auto" }}>{JSON.stringify(output, null, 2)}</pre>}</details>
    </>}
    <p>Action binding: {detail.scenario_config?.action_binding ? `intent ${detail.scenario_config.action_binding.intent_id}` : "Unavailable / unbound"}</p>
    {detail.scenario_config?.action_binding && <><div className="mono">plan_sha256: {detail.scenario_config.action_binding.plan_sha256}</div><div className="mono">network_state_sha256: {detail.scenario_config.action_binding.network_state_sha256}</div></>}
    <p>Modeled evidence expiry: {Number.isFinite(expiry) ? `${expiry <= Math.max(now, Date.now()) ? "Expired" : "Expires"} ${new Date(expiry).toISOString()} (browser clock; server authoritative)` : "Unavailable (not reported)"}. Server policy revalidates exact action/network hashes, tenant, completion, risk and expiry at execution; the UI does not grant authorization.</p>
    <ExecutionPolicy policy={detail.execution_policy} />
    <details><summary>Persisted model and audit provenance</summary><pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", maxHeight: 240, overflow: "auto" }}>{JSON.stringify({ model_versions: detail.model_versions, audit_provenance: detail.audit_provenance }, null, 2)}</pre></details>
  </section>;
}

const finite = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);

/** Server policy floors (C18). Only modeled runs report them; the backend schema is untyped, so read defensively. */
function ExecutionPolicy({ policy }: { policy: SimulationDetail["execution_policy"] }) {
  if (!policy || typeof policy !== "object") return <p>Execution policy: not reported (only modeled runs are evaluated against server policy floors).</p>;
  const floors = policy.policy_floors && typeof policy.policy_floors === "object" ? policy.policy_floors : null;
  const respects = policy.limits_respect_policy;
  return <div role="group" aria-label="Execution policy">
    <p>Server policy floors: {floors && finite(floors.max_loss_pct) && finite(floors.max_latency_ms) && finite(floors.min_throughput_mbps)
      ? `loss at most ${floors.max_loss_pct} %, latency at most ${floors.max_latency_ms} ms, throughput at least ${floors.min_throughput_mbps} Mbps`
      : "Unavailable (malformed)"}. Run limits may be stricter, never weaker.</p>
    {respects === true ? <p>This run's limits respect the policy floors.</p>
      : <p role="alert">{respects === false
        ? "This run's limits are weaker than the server policy floors: it can never authorize a high-impact execution (SIMULATION_POLICY_VIOLATION)."
        : "Whether this run's limits respect the policy floors is unknown; the server decides at execution."}</p>}
  </div>;
}

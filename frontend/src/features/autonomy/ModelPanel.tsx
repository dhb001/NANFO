import { useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Panel } from "@/shared/ui/Panel";
import { Button } from "@/shared/ui/Button";
import { toErrorMessage } from "@/shared/lib/errors";
import { formatTimestamp } from "@/shared/lib/format";
import { useOperatorSession } from "./operatorSession";
import { diagnoseModel, getModelDiagnostics } from "./modelApi";
import { AUTONOMY_FRESH_MS } from "./hooks";

export function ModelPanel({ now }: { now: number }) {
  const session = useOperatorSession();
  const [history, setHistory] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const saving = useRef(false);
  const query = useQuery({ queryKey: ["autonomy-operator", ...session.identity, "model"],
    queryFn: ({ signal }) => { session.assertCurrent(); return getModelDiagnostics(session.token, session.networkId!, session.workspaceId!, signal); },
    enabled: session.enabled, retry: false, gcTime: 0, refetchOnWindowFocus: false });
  const fresh = query.isSuccess && !query.isFetching && now - query.dataUpdatedAt < AUTONOMY_FRESH_MS;
  const mutation = useMutation({ mutationFn: () => {
    session.assertCurrent(true);
    if (!fresh || query.data?.status !== "operator_registered" || !query.data.model?.history_references.includes(history)) throw new Error("Refresh registry and select an approved history reference.");
    return diagnoseModel(session.token, session.networkId!, session.workspaceId!, history);
  }, retry: false, onSettled: session.reconcile });
  async function run() {
    if (saving.current) return;
    saving.current = true;
    setNotice(null);
    try {
      const result = await mutation.mutateAsync();
      session.assertCurrent();
      setNotice(`Recorded diagnostic ${result.diagnostic_id}. Historical inference only; execution not applied.`);
    } catch (error) { setNotice(`Inference not confirmed. ${toErrorMessage(error)} No automatic retry.`); }
    finally { saving.current = false; }
  }
  const data = query.data;
  return <Panel title="Frozen model diagnostics" subtitle="Pinned registry, explicit historical inference, no model uploads">
    <div className="autonomy-stack">
      <Button tone="ghost" disabled={!session.enabled || query.isFetching || mutation.isPending} onClick={() => void query.refetch()}>Refresh model registry</Button>
      {query.isPending && <p role="status">Loading model registry...</p>}
      {query.isError && <p role="alert">Model read unavailable. {toErrorMessage(query.error)} Retry with Refresh model registry.</p>}
      {data && !fresh && <p role="status">Model registry is stale or refreshing. Inference is disabled until a fresh successful read.</p>}
      <p>Server status: <strong>{data?.status ?? "unknown"}</strong>. Live history: <strong>{data?.live_history_status ?? "unknown"}</strong>. Safety authorization: false. Production dispatch: false.</p>
      {data?.reasons.length ? <ul>{data.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul> : null}
      {data?.model ? <>
        <dl><div><dt>Registered model / checkpoint</dt><dd>{data.model.model_id} / {data.model.checkpoint_id}</dd></div>
          <div><dt>Pinned checkpoint SHA-256</dt><dd className="mono">{data.model.checkpoint_sha256}</dd></div>
          <div><dt>Recorded benchmark</dt><dd>{data.model.benchmark_status}: {data.model.benchmark_scope}</dd></div></dl>
        <ul>{data.model.benchmark_limitations.map((limit, i) => <li key={i}>{limit}</li>)}</ul>
        <label>Operator history reference<select value={history} disabled={!session.canWrite || mutation.isPending} onChange={(event) => setHistory(event.target.value)}>
          <option value="">Select registered historical input</option>
          {data.model.history_references.map((id) => <option key={id} value={id}>{id}</option>)}
        </select></label>
        {!data.model.history_references.length && <p>No compatible operator-provisioned historical input is available.</p>}
        <Button disabled={!session.canWrite || !fresh || data.status !== "operator_registered" || !data.model.history_references.includes(history) || mutation.isPending} onClick={() => void run()}>
          {mutation.isPending ? "Running bounded inference..." : "Run historical inference"}</Button>
      </> : <p>No registered model available. No local training files are read or overwritten.</p>}
      {!session.canWrite && <p>Read-only: inference requires write:config and execute:rollback.</p>}
      <p>Probabilities are action probabilities, not safety confidence. Historical inference never dispatches, updates training, or establishes compatible live observations.</p>
      {notice && <p role="alert">{notice}</p>}
      <h3>Recorded diagnostic history</h3>
      {!data?.diagnostics.length && <p>No recorded inference diagnostics for this network.</p>}
      {data?.diagnostics.map((record) => <article key={record.diagnostic_id} className="autonomy-decision autonomy-stack">
        <h4>Historical inference / {formatTimestamp(record.created_at)}</h4>
        <p>{record.result.model_id} / {record.result.checkpoint_id} / {record.result.history_reference}. Actor: {record.actor_id}.</p>
        <p>Live: false. Execution: {record.result.execution}. Safety authorized: false.</p>
        <p>Action {record.result.action}: {record.result.action_path.join(" -> ")} (model proposal, not observed traversal). Value estimate: {record.result.value}.</p>
        <div role="group" aria-label="Action probabilities, not safety confidence">{record.result.probabilities.map((p, index) => <label key={index}>Action {index}: {(p * 100).toFixed(2)}%<meter min={0} max={1} value={p} aria-label={`Action ${index} probability`} /></label>)}</div>
        <p>Timings: inference {record.result.inference_seconds}s; validation plus inference {record.result.artifact_validation_and_inference_seconds}s; subprocess {record.result.subprocess_seconds}s. Not network convergence or SPF timing.</p>
        <dl><div><dt>Model weights SHA-256</dt><dd className="mono">{record.result.checkpoint_weights_sha256}</dd></div>
          <div><dt>Model input SHA-256</dt><dd className="mono">{record.result.input_sha256}</dd></div>
          <div><dt>History SHA-256</dt><dd className="mono">{record.result.history_sha256}</dd></div></dl>
        <details><summary>Inference provenance and evidence</summary><pre className="autonomy-evidence">{JSON.stringify(record, null, 2)}</pre></details>
      </article>)}
    </div>
  </Panel>;
}

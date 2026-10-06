import { lazy, Suspense, useEffect, useRef, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { useSessionScope } from "@/features/auth/sessionScope";
import { Panel } from "@/shared/ui/Panel";
import { Button } from "@/shared/ui/Button";
import { Badge } from "@/shared/ui/Badge";
import { AsyncState } from "@/shared/ui/AsyncState";
import { formatTimestamp } from "@/shared/lib/format";
import { toErrorMessage } from "@/shared/lib/errors";
import { useAuthStore } from "@/shared/state/auth-store";
import { AUTONOMY_FRESH_MS, useAutonomy } from "./hooks";
import { buildAutonomyUpdate, describeAutonomyError, describeConfidence } from "./logic";
import type { AutonomyMode } from "./types";
import { SafetyCertificate } from "./SafetyCertificate";
import "./autonomy.css";

const OperatorPanels = lazy(() => import("./OperatorPanels").then((module) => ({ default: module.OperatorPanels })));

const providerLabels = {
  qualification: "Qualified checkpoint",
  observer: "Compatible observations",
  inference: "Frozen inference",
  safety: "Calibrated safety bounds",
  executor: "Authorized durable executor",
} as const;

const reasonLabels: Record<string, string> = {
  qualified_checkpoint_unavailable: "No qualified checkpoint is installed.",
  observation_contract_incompatible: "Observations are incompatible with the frozen model contract.",
  frozen_inference_unavailable: "Qualified frozen inference is unavailable.",
  calibrated_safety_unavailable: "Physically calibrated safety bounds are unavailable.",
  autonomous_executor_unavailable: "The server-authorized autonomous executor is unavailable.",
};

export function AutonomyPage() {
  const { key } = useSessionScope();
  return <AutonomyPageContent key={key} />;
}

function AutonomyPageContent() {
  const { authority } = useSessionScope();
  const { status: query, update, stop, enabled, canRead, canWrite, networkId, workspaceId, organizationId } = useAutonomy();
  const userId = useAuthStore((state) => state.userId);
  const [mode, setMode] = useState<AutonomyMode>("monitor");
  const [hash, setHash] = useState("");
  const [expiry, setExpiry] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const [stopNotice, setStopNotice] = useState<string | null>(null);
  const [panel, setPanel] = useState("status");
  const [now, setNow] = useState(Date.now());
  const saving = useRef(false);
  const stopping = useRef(false);
  const stopAttempt = useRef(0);
  useEffect(() => { setHash(""); setExpiry(""); }, [authority]);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, []);

  const data = query.data;
  const fresh = enabled && query.isSuccess && !query.isFetching && Boolean(data) &&
    now - query.dataUpdatedAt < AUTONOMY_FRESH_MS;
  const autonomousReady = fresh && data?.ready === true && data.blocked_reasons.length === 0 &&
    Object.values(data.providers).every((provider) => provider.status === "ready") &&
    data.online_learning === false && data.production_dispatch === false;
  const busy = update.isPending || stop.isPending;
  const reasons = data ? [...new Set([...data.blocked_reasons,
    ...Object.values(data.providers).flatMap((provider) => provider.reasons),
    ...(data.last_observation?.reasons ?? [])])] : [];

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!canWrite || !fresh || !data || busy || saving.current || stopping.current || !networkId ||
        (mode === "autonomous" && !autonomousReady)) return;
    const attempt = stopAttempt.current;
    setNotice(null);
    try {
      const input = buildAutonomyUpdate(networkId, mode, hash, expiry, data.revision);
      saving.current = true;
      const result = await update.mutateAsync(input);
      if (attempt === stopAttempt.current) {
        setStopNotice(null);
        setNotice(result.pendingApproval
          ? `Recorded as a pending autonomous request (two-person rule). The mode is unchanged until a different authorized user submits the identical request${result.pendingApprovalExpiresAt ? ` before ${formatTimestamp(result.pendingApprovalExpiresAt)}` : ""}.`
          : "Configuration response received. Consult the confirmed mode below; this is not dispatch or verification.");
      }
    } catch (error) {
      setNotice(`Mode change not confirmed. ${describeAutonomyError(error)} No automatic retry or reapproval. Review refreshed status and explicitly apply any new change.`);
    } finally {
      saving.current = false;
    }
  }

  async function emergencyStop() {
    if (!enabled || !canWrite || stopping.current) return;
    stopping.current = true;
    stopAttempt.current += 1;
    setNotice(null);
    setStopNotice("Stop requested. Latch unconfirmed until the backend responds.");
    try {
      const result = await stop.mutateAsync();
      setStopNotice(result.emergency_stopped === true
        ? `Backend confirmed the emergency latch. Cancellation: ${result.cancellation_status}. A latch is not proof of verified cancellation; consult refreshed status.`
        : "Stop response received, but latch unconfirmed. Refresh status or retry stop; do not assume execution stopped.");
    } catch (error) {
      setStopNotice(`Stop failed: latch unconfirmed. ${describeAutonomyError(error)} Refresh status or retry stop; do not assume execution stopped.`);
    } finally {
      stopping.current = false;
    }
  }

  if (!canRead) return <AsyncState title="Permission denied" description="Autonomy requires read:telemetry. No status is requested." />;
  if (!networkId || !workspaceId || !organizationId) return <AsyncState title="Select a network" description="Autonomy is bounded to one network in the current organization and workspace."
    action={<Link to="/ops/overview">Select context in Overview</Link>} />;

  return <div className="autonomy-page">
    <header className="autonomy-stack">
      <h1>Governed Autonomy</h1>
      <p>Monitor by default. Recommendations never dispatch. Autonomous operation remains unavailable until backend readiness gates pass.</p>
      <p className="mono">Network: {networkId}<br />Workspace: {workspaceId}</p>
      <div className="autonomy-actions"><Badge text="Online learning disabled" tone="neutral" /><Badge text="Production dispatch disabled" tone="warn" /></div>
    </header>

    <section className="autonomy-stop" aria-labelledby="autonomy-stop-title">
      <h2 id="autonomy-stop-title">Emergency stop</h2>
      <p>Immediately request a durable latch for this network and cancellation of Autonomy-owned execution. Enrolled timed overrides are restored by the server worker; unrelated manual executions are not targeted. No confirmation dialog.</p>
      <div><Button tone="danger" disabled={!enabled || !canWrite || stop.isPending} onClick={() => void emergencyStop()}>
        {stop.isPending ? "Requesting emergency stop..." : "Emergency stop"}
      </Button></div>
      {!canWrite ? <p>Read-only: changes and stop require write:config and execute:rollback, plus current writable membership enforced by the backend.</p> : null}
      {stopNotice ? <p role="alert" className="autonomy-warning">{stopNotice}</p> : null}
      {data ? <p>Last reported latch: <strong>{data.emergency_stopped ? "latched" : "not latched"}</strong>. Cancellation: <strong>{data.cancellation_status}</strong>.
        {data.stopped_at ? ` Stopped at ${formatTimestamp(data.stopped_at)} by ${data.stopped_by_user_id ?? "unreported actor"}.` : ""}</p> : null}
      <p>A latch never clears itself. An explicit mode change may clear it only when backend gates and unresolved-operation checks allow it.</p>
    </section>

    <nav className="autonomy-actions" aria-label="Autonomy panels">
      {[["status", "Status and decisions"], ["model", "Model diagnostics"], ["configuration", "Versioned configuration"], ["overrides", "Timed overrides"]].map(([id, label]) =>
        <Button key={id} tone={panel === id ? "primary" : "ghost"} aria-pressed={panel === id} aria-controls={`autonomy-${id}-panel`} onClick={() => setPanel(id)}>{label}</Button>)}
    </nav>
    {panel !== "status" && <div id={`autonomy-${panel}-panel`}><Suspense fallback={<p>Loading operator panel...</p>}>
      <OperatorPanels panel={panel} now={now} control={data} controlFresh={fresh} stopPending={stop.isPending || stopNotice !== null} refreshControl={() => void query.refetch()} />
    </Suspense></div>}

    <div id="autonomy-status-panel" hidden={panel !== "status"}>
    <div className="autonomy-stack">
    <div className="autonomy-actions"><Button tone="ghost" disabled={!enabled || query.isFetching} onClick={() => void query.refetch()}>
      {query.isFetching ? "Refreshing status..." : "Refresh status"}
    </Button></div>
    {query.isPending ? <AsyncState title="Loading autonomy status" description="Readiness and current mode are not yet confirmed." /> : null}
    {query.isError ? <div role="alert"><AsyncState title="Autonomy status unavailable" description={`${toErrorMessage(query.error)} Last-known data is not current authorization. Retry with Refresh status.`} /></div> : null}
    {data && !fresh ? <p role="status" className="autonomy-warning">Status is stale or refreshing. Mode changes are disabled; emergency stop remains available to authorized operators.</p> : null}

    <div className="autonomy-grid">
      <Panel title="Backend status" subtitle="Requested mode is not evidence of an intervention">
        {data ? <div className="autonomy-stack">
          <dl>
            <div><dt>{fresh ? "Confirmed mode" : "Last-known mode"}</dt><dd data-testid="autonomy-mode">{data.mode}</dd></div>
            <div><dt>Backend lifecycle</dt><dd>{data.status}</dd></div>
            <div><dt>Autonomous readiness</dt><dd>{autonomousReady ? "Backend reports ready; each request is rechecked" : "Unavailable"}</dd></div>
            <div><dt>Checkpoint SHA-256</dt><dd className="mono">{data.checkpoint_sha256 ?? "No checkpoint selected"}</dd></div>
            <div><dt>Approval expiry</dt><dd>{data.approval_expires_at ? formatTimestamp(data.approval_expires_at) : "No approval"}</dd></div>
            <div><dt>Approved by</dt><dd>{data.approved_by_user_id ?? "No approving actor"}</dd></div>
            <div><dt>Pending two-person approval</dt><dd>{data.pending_approval
              ? `${data.pending_approval.mode} requested by ${data.pending_approval.requested_by_user_id === userId ? "you (a different user must confirm)" : data.pending_approval.requested_by_user_id} at revision ${data.pending_approval.expected_revision}; expires ${formatTimestamp(data.pending_approval.expires_at)}`
              : "None"}</dd></div>
            <div><dt>Active execution</dt><dd className="mono">{data.active_execution_id ?? "None reported"}</dd></div>
            <div><dt>Last status read / control revision</dt><dd>{formatTimestamp(new Date(query.dataUpdatedAt).toISOString())} / {data.revision}</dd></div>
          </dl>
          <h4>All reported gate reasons</h4>
          {reasons.length ? <ul>{reasons.map((reason) => <li key={reason}>{reasonLabels[reason] ? `${reasonLabels[reason]} ` : ""}<code>{reason}</code></li>)}</ul>
            : <p>No gate reasons reported. This is not a global stability proof or evidence of measured benefit.</p>}
          <dl>{Object.entries(providerLabels).map(([key, label]) => {
            const provider = data.providers[key as keyof typeof providerLabels];
            return <div key={key}><dt>{label}</dt><dd>{provider.status} <span className="mono">({provider.provider_id})</span></dd></div>;
          })}</dl>
        </div> : <p>No confirmed status. Safe UI default: monitor; backend state is unknown.</p>}
      </Panel>

      <Panel title="Operator controls" subtitle="One network, exact frozen model, bounded approval">
        <form onSubmit={(event) => void save(event)} className="autonomy-stack">
          <label>Requested mode<select value={mode} disabled={!canWrite || busy} onChange={(event) => setMode(event.target.value as AutonomyMode)}>
            <option value="monitor">Monitor (no dispatch)</option>
            <option value="recommend">Recommendation (no dispatch)</option>
            <option value="autonomous" disabled={!autonomousReady}>Autonomous{!autonomousReady ? " (unavailable)" : ""}</option>
          </select></label>
          <label>Checkpoint SHA-256<input value={hash} onChange={(event) => setHash(event.target.value)} disabled={!canWrite || busy}
            maxLength={64} pattern="[a-fA-F0-9]{64}" autoComplete="off" spellCheck={false} placeholder="64 hexadecimal characters; no model path" /></label>
          <label>Approval expiry (local time)<input type="datetime-local" value={expiry} onChange={(event) => setExpiry(event.target.value)} disabled={!canWrite || busy} /></label>
          <p>Expiry is sent as UTC. Autonomous approval requires both fields, expires within one hour, and is bound by the backend to the current actor, network and checkpoint. Monitor and recommendation do not retain approval expiry. Blank fields send null, not a latest-model pointer.</p>
          <p>A completed training run, including one that failed its quality gate, does not qualify a model. This UI reads no local training artifacts and never selects or approves a checkpoint automatically.</p>
          <p>Monitor and recommendation record non-actuating observations or proposals only. Changing mode is not verified execution or measured performance improvement.</p>
          <p>Each submission uses the last confirmed control revision ({data?.revision ?? "unavailable"}). A conflict refreshes status; it never retries or renews approval automatically.</p>
          <Button type="submit" disabled={!canWrite || !fresh || busy || (mode === "autonomous" && !autonomousReady)}>{update.isPending ? "Applying configuration..." : "Apply configuration"}</Button>
          {notice ? <p role="alert">{notice}</p> : null}
        </form>
      </Panel>
    </div>

    <Panel title="Last observation" subtitle="Backend freshness and contract compatibility are separate gates">
      {data?.last_observation ? <div className="autonomy-stack">
        <p>Observed: {data.last_observation.observed_at ? formatTimestamp(data.last_observation.observed_at) : "Not available"}. Collected: {formatTimestamp(data.last_observation.collected_at)}.</p>
        <p>Fresh at collection: {data.last_observation.fresh ? "yes" : "no"}; compatible: {data.last_observation.compatible ? "yes" : "no"}; age at collection: {data.last_observation.age_seconds ?? "unknown"} seconds.</p>
        <p className="mono">{data.last_observation.provider_id} / {data.last_observation.contract}</p>
      </div> : <p>No observation reported. Ordinary telemetry does not establish compatible inference input or calibrated safety bounds.</p>}
    </Panel>

    <Panel title="Decision history" subtitle={data ? `Latest ${data.decisions.length} durable decisions; backend history limit ${data.history_limit}` : "No confirmed history"}>
      <div className="autonomy-stack">
        <p>Safety certificates are conditional one-step discrete-time checks under stated bounds, not a global or continuous-time stability proof. Acceptance, switch verification and measured performance improvement are distinct.</p>
        {!data?.decisions.length ? <p>No decisions reported for this network. No intervention or safety certificate is implied.</p> : data.decisions.map((decision) => <article key={decision.decision_id} className="autonomy-decision autonomy-stack">
          <h4>{decision.status} <span className="mono">{decision.decision_id}</span></h4>
          <p>{formatTimestamp(decision.created_at)} | mode {decision.mode} | revision {decision.control_revision}</p>
          <p>Execution: {decision.execution_id ?? "None reported"}. Verification: {decision.verification?.status ?? "Not reported"}.</p>
          <p>Safety assessment: {decision.safety ? `${decision.safety.admissible ? "conditionally admissible" : "not admissible"} (${decision.safety.model_version})` : "No assessment reported"}.</p>
          <ConfidenceLine confidence={decision.confidence ?? decision.proposal?.confidence} />
          {decision.repeat_count && decision.repeat_count > 1 ? <p>Stands for {decision.repeat_count} identical no-change cycles{decision.last_seen_at ? `; last seen ${formatTimestamp(decision.last_seen_at)}` : ""}.</p> : null}
          <SafetyCertificate safety={decision.safety} now={now} />
          {!decision.safety?.certificate ? <p>No structured certificate reported.</p> : null}
          {decision.reasons.length ? <ul>{decision.reasons.map((reason, index) => <li key={`${reason}:${index}`}><code>{reason}</code></li>)}</ul> : null}
          <details><summary>Decision evidence and conditional assessment</summary>
            <pre className="autonomy-evidence">{JSON.stringify({ checkpoint_sha256: decision.checkpoint_sha256, actor_id: decision.actor_id,
              observation: decision.observation, proposal: decision.proposal, safety: decision.safety,
              verification: decision.verification, evidence: decision.evidence, updated_at: decision.updated_at }, null, 2)}</pre>
          </details>
        </article>)}
      </div>
    </Panel>
    </div>
    </div>
  </div>;
}

function ConfidenceLine({ confidence }: { confidence: Parameters<typeof describeConfidence>[0] }) {
  const { text, calibrated } = describeConfidence(confidence);
  return <p><Badge text={calibrated ? "calibrated" : confidence ? "uncalibrated" : "confidence unavailable"} tone={calibrated ? "info" : "warn"} /> {text}</p>;
}

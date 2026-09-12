import { useRef, useState, type FormEvent } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Panel } from "@/shared/ui/Panel";
import { Button } from "@/shared/ui/Button";
import { ApiClientError, toErrorMessage } from "@/shared/lib/errors";
import { getIntentDetail } from "@/features/intent/api";
import { mapExecutionDiagnostics } from "@/features/intent/logic";
import { useAuthStore } from "@/shared/state/auth-store";
import { useOperatorSession } from "./operatorSession";
import { AUTONOMY_FRESH_MS, AUTONOMY_POLL_MS } from "./hooks";
import { uuid } from "./contractChecks";
import { actOnOverride, createOverride, getOverrides } from "./overrideApi";
import type { AutonomyMode, AutonomyStatus } from "./types";
import type { TimedOverride } from "./overrideTypes";

export function OverridePanel({ now, control, controlFresh, stopPending, refreshControl }: {
  now: number; control: AutonomyStatus | undefined; controlFresh: boolean; stopPending: boolean; refreshControl: () => void;
}) {
  const session = useOperatorSession();
  const [intentId, setIntentId] = useState("");
  const [executionId, setExecutionId] = useState("");
  const [selected, setSelected] = useState<{ intent: string; execution: string } | null>(null);
  const [duration, setDuration] = useState(300);
  const [reason, setReason] = useState("");
  const [returnMode, setReturnMode] = useState<AutonomyMode>("monitor");
  const [returnReason, setReturnReason] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const busy = useRef(false);
  const query = useQuery({ queryKey: ["autonomy-operator", ...session.identity, "overrides"],
    queryFn: ({ signal }) => { session.assertCurrent(); return getOverrides(session.token!, session.networkId!, session.workspaceId!, signal); },
    enabled: session.enabled, retry: false, gcTime: 0, refetchIntervalInBackground: false,
    refetchInterval: (q) => q.state.error instanceof ApiClientError && [401, 403].includes(q.state.error.status ?? 0) ? false : AUTONOMY_POLL_MS });
  const detail = useQuery({ queryKey: ["autonomy-operator", ...session.identity, "override-intent", selected],
    queryFn: async ({ signal }) => {
      session.assertCurrent();
      const { data } = await getIntentDetail(session.token!, selected!.intent, session.workspaceId!, signal);
      if (data.network_id !== session.networkId || data.workspace_id !== session.workspaceId || data.intent_id !== selected?.intent ||
          !uuid(data.execution_provenance.execution_id) || data.execution_provenance.execution_id !== selected.execution) throw new Error("Selected intent/execution does not match this network.");
      return data;
    }, enabled: session.enabled && Boolean(selected), retry: false, gcTime: 0, refetchOnWindowFocus: false });
  const fresh = controlFresh && query.isSuccess && !query.isFetching && now - query.dataUpdatedAt < AUTONOMY_FRESH_MS && query.data.control_revision === control?.revision;
  const stopped = stopPending || control?.emergency_stopped !== false;
  const unresolved = Boolean(query.data?.overrides.some((item) => item.status === "holding" || item.status === "restoring"));
  const diagnostics = detail.data ? mapExecutionDiagnostics(detail.data) : null;
  const executingApprover = detail.data?.execution_provenance.approved_by_user_id;
  const selectedVerified = detail.isSuccess && !detail.isFetching && now - detail.dataUpdatedAt < AUTONOMY_FRESH_MS &&
    detail.data.status === "execution_completed" && uuid(executingApprover) && executingApprover === useAuthStore.getState().profile?.user_id &&
    diagnostics?.verificationStatus === "readback verified" && detail.data.execution_provenance.phase === "completed" &&
    detail.data.execution_provenance.uncertain !== true && detail.data.execution_provenance.cancel_requested !== true && !diagnostics.rollbackAttempted && !diagnostics.rollbackStatus;
  const autonomousApproval = fresh && control?.mode === "autonomous" && control.ready && control.blocked_reasons.length === 0 &&
    Object.values(control.providers).every((provider) => provider.status === "ready") && control.checkpoint_sha256 &&
    control.approved_by_user_id === useAuthStore.getState().profile?.user_id && control.approval_expires_at && Date.parse(control.approval_expires_at) > now + duration * 1000;
  const mutation = useMutation({ mutationFn: async (request: { action: "enroll" } | { action: "cancel" | "return"; row: TimedOverride }) => {
    session.assertCurrent(true);
    if (request.action === "enroll") {
      if (!fresh || stopped || unresolved || !selectedVerified || !selected || (returnMode === "autonomous" && !autonomousApproval)) throw new Error("Fresh verified selection, control revision and approval gates are required.");
      return createOverride(session.token!, session.workspaceId!, { network_id: session.networkId!, intent_id: selected.intent,
        execution_id: selected.execution, expected_revision: control!.revision, reason: reason.trim(), duration_seconds: duration, return_mode: returnMode });
    }
    if (request.action === "return" && (!fresh || stopped || !request.row.restored_at || !["restored", "return_blocked"].includes(request.row.status))) throw new Error("STOP or unresolved restoration blocks return. Refresh status.");
    return actOnOverride(session.token!, session.networkId!, session.workspaceId!, request.row.override_id, request.action,
      request.action === "return" ? { expected_revision: control!.revision, reason: returnReason.trim() } : undefined);
  }, retry: false, onSettled: session.reconcile });
  async function request(input: Parameters<typeof mutation.mutateAsync>[0], event?: FormEvent) {
    event?.preventDefault(); if (busy.current) return; busy.current = true; setNotice(null);
    try {
      const result = await mutation.mutateAsync(input); session.assertCurrent();
      setNotice(`Server override status: ${result.status}. ${input.action === "cancel" ? "Cancellation requests restoration, not immediate verified success." : "Consult refreshed control and restoration evidence; no client-side mode change."}`);
    } catch (error) { setNotice(`Override request not confirmed. ${toErrorMessage(error)} No automatic retry or reapproval. Refresh and explicitly submit again.`); }
    finally { busy.current = false; }
  }
  return <Panel title="Timed manual overrides" subtitle="Enroll an owned verified execution; the independent server worker restores it">
    <div className="autonomy-stack">
      <Button tone="ghost" disabled={!session.enabled || query.isFetching} onClick={() => { void query.refetch(); refreshControl(); }}>Refresh override status</Button>
      {query.isPending && <p role="status">Loading override history...</p>}
      {query.isError && <p role="alert">Override history unavailable. {toErrorMessage(query.error)} Retry with Refresh override status.</p>}
      {!fresh && <p role="status">Fresh matching control and override revisions are required for enrollment and return.</p>}
      {stopped && <p role="alert">STOP dominates enrollment, expiry and return. Cancellation may still request restoration; no override action clears the latch.</p>}
      <p>Enrollment holds monitor mode. Expiry/countdown is server-owned; this browser never restores configuration or switches modes. A return request is not autonomous activation.</p>
      <form className="autonomy-stack" onSubmit={(event) => void request({ action: "enroll" }, event)}>
        <fieldset className="autonomy-stack" disabled={!session.canWrite || mutation.isPending}><legend>Selected manual execution</legend>
          <label>Override intent UUID<input value={intentId} onChange={(event) => { setIntentId(event.target.value); setSelected(null); }} /></label>
          <label>Override execution UUID<input value={executionId} onChange={(event) => { setExecutionId(event.target.value); setSelected(null); }} /></label>
          <Button type="button" tone="ghost" disabled={!uuid(intentId) || !uuid(executionId) || detail.isFetching} onClick={() => {
            if (selected?.intent === intentId && selected.execution === executionId) void detail.refetch();
            else setSelected({ intent: intentId, execution: executionId });
          }}>Inspect selected execution</Button>
          {detail.isFetching && <p role="status">Inspecting exact selected execution...</p>}
          {detail.isError && <p role="alert">Selection unavailable. {toErrorMessage(detail.error)}</p>}
          {detail.data && <p>Selected execution status: {detail.data.status}. Readback: {diagnostics?.verificationStatus ?? "unavailable"}. {selectedVerified ? "Eligible for server enrollment checks." : "Not eligible for enrollment."}</p>}
          <label>Override duration (seconds)<input type="number" required min={1} max={3600} step={1} value={Number.isNaN(duration) ? "" : duration} onChange={(event) => setDuration(event.target.valueAsNumber)} /></label>
          <label>Override reason<input required maxLength={1000} value={reason} onChange={(event) => setReason(event.target.value)} /></label>
          <label>Return mode<select value={returnMode} onChange={(event) => setReturnMode(event.target.value as AutonomyMode)}>
            <option value="monitor">Monitor</option><option value="recommend">Recommendation (server gates apply)</option>
            <option value="autonomous" disabled={!autonomousApproval}>Autonomous return (prior unexpired approval required)</option>
          </select></label>
        </fieldset>
        <p>Server enrollment rechecks current journal ownership and readback age, exact command identity, network, actor and revision. Historical detail alone is not current policy proof.</p>
        <Button type="submit" disabled={!session.canWrite || !fresh || stopped || unresolved || !selectedVerified || !reason.trim() || mutation.isPending || (returnMode === "autonomous" && !autonomousApproval)}>Enroll timed override</Button>
      </form>
      {!session.canWrite && <p>Read-only: enrollment, cancellation and return require write:config and execute:rollback.</p>}
      {notice && <p role="alert">{notice}</p>}
      <label>Explicit return reason<input maxLength={1000} value={returnReason} disabled={!session.canWrite || mutation.isPending} onChange={(event) => setReturnReason(event.target.value)} /></label>
      {!query.data?.overrides.length && <p>No timed overrides recorded for this network.</p>}
      {query.data?.overrides.map((row) => <article key={row.override_id} className="autonomy-decision autonomy-stack">
        <h4>Override {row.status}</h4><p className="mono">{row.override_id}</p>
        <p>Intent {row.intent_id}; execution {row.execution_id}. Actor {row.actor_id}: {row.reason}</p>
        <p>Server expiry: {row.expires_at}. {Date.parse(row.expires_at) > now ? `Approximate countdown: ${Math.ceil((Date.parse(row.expires_at) - now) / 1000)} seconds (browser clock).` : "Expiry reached by browser clock; awaiting server lifecycle, not proof of restoration."}</p>
        <p>Prior {row.prior_mode} / revision {row.prior_revision}; hold revision {row.hold_revision}; requested return {row.return_mode}.</p>
        <p>Restoration: {row.restored_at ? `server verified at ${row.restored_at}` : "not verified"}. Verification status: {typeof row.verification?.status === "string" ? row.verification.status : "not reported"}. Attempts: {row.restoration_attempts}.</p>
        <p>Return: {row.returned_at ? `server recorded at ${row.returned_at}; consult current mode` : "not confirmed"}. Cancellation ID: {row.cancellation_id ?? "none"}.</p>
        {row.reasons.length > 0 && <ul>{row.reasons.map((value, i) => <li key={i}>{value}</li>)}</ul>}
        <div className="autonomy-actions"><Button tone="danger" disabled={!session.canWrite || mutation.isPending || !["holding", "restoring"].includes(row.status)} onClick={() => void request({ action: "cancel", row })}>Request restoration</Button>
          <Button disabled={!session.canWrite || !fresh || stopped || mutation.isPending || !returnReason.trim() || !row.restored_at || !["restored", "return_blocked"].includes(row.status)} onClick={() => void request({ action: "return", row })}>Request gated return</Button></div>
        <p>Return rechecks model identity, live observer, calibrated safety, executor, prior approval and current revision. Blocked return stays monitor; no fake autonomous state.</p>
        <details><summary>Override identity and restoration evidence</summary><pre className="autonomy-evidence">{JSON.stringify(row, null, 2)}</pre></details>
      </article>)}
    </div>
  </Panel>;
}

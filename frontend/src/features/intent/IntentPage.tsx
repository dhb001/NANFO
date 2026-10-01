import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import { useExecuteIntent, useIntentDetail, useValidateIntent, useIntentHistory } from "@/features/intent/hooks";
import { useAuthStore } from "@/shared/state/auth-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { Panel } from "@/shared/ui/Panel";
import { Button } from "@/shared/ui/Button";
import { QueryState } from "@/shared/ui/QueryState";
import { Badge } from "@/shared/ui/Badge";
import {
  explainabilitySummary,
  intentSceneObjectId,
  isIntentTerminalStatus,
  mapExecutionDiagnostics,
  mapIntentLifecycle,
  shouldRefetchIntentFromRealtime,
  canCancelIntent,
} from "@/features/intent/logic";
import { displayValue, formatTimestamp } from "@/shared/lib/format";
import { useLiveStore } from "@/features/realtime/store";
import { AsyncState } from "@/shared/ui/AsyncState";
import { useUiStore } from "@/shared/state/ui-store";
import { describeApiError, toErrorMessage } from "@/shared/lib/errors";
import { useIsNarrowViewport } from "@/shared/lib/viewport";
import { canExecuteIntent } from "@/shared/lib/intent";
import { intentConfidenceBandTone, intentQueueStatusTone, intentStatusTone, statusLabel } from "@/shared/lib/statusTones";
import { hasPermission } from "@/features/auth/permissions";
import { useExecutionModeStore } from "@/shared/state/execution-mode-store";
import { LabActionFields } from "@/features/intent/LabActionFields";
import type { ExecuteIntentRequest } from "@/shared/types/intent";
import { PathEvidencePanel } from "./PathEvidencePanel";
import { SceneReconciliationStatus } from "@/features/realtime/SceneReconciliationStatus";
import { useSessionScope } from "@/features/auth/sessionScope";
import { useUrlSelection } from "@/shared/lib/urlSelection";
import { randomId } from "@/shared/lib/uid";
import { HANDOFF_QUERY_PARAMS, INTENT_FORM_ACTIONS, readIntentHandoffState, readUntrustedIntentQuery, type IntentPrefillReading } from "./handoff";
import { intentConflictGuidance, isUnknownOutcome, type IntentConflictGuidance } from "./conflicts";
import { ApprovalBindingSummary, ValidationDisclosure } from "./IntentEvidence";

/** One validate submission: its key is reused only to retry the same draft after an unknown outcome (C3). */
interface ValidationAttempt {
  key: string;
  draft: string;
  outcome: "pending" | "unknown" | "done";
}

export function IntentPage() {
  const { key } = useSessionScope();
  const location = useLocation();
  // A router-state handoff is applied once per navigation, not again after a scope remount.
  const [consumedHandoff, setConsumedHandoff] = useState<string | null>(null);
  const routedHandoff = consumedHandoff === location.key ? null : readIntentHandoffState(location.state);
  return <IntentPageContent key={key} routedHandoff={routedHandoff} onHandoffApplied={() => setConsumedHandoff(location.key)} />;
}

function IntentPageContent({ routedHandoff, onHandoffApplied }: { routedHandoff: IntentPrefillReading | null; onHandoffApplied: () => void }) {
  const session = useSessionScope();
  const token = useAuthStore((state) => state.accessToken);
  const profile = useAuthStore((state) => state.profile);
  const mode = useExecutionModeStore((state) => state.mode);
  const workspaceId = useWorkspaceStore((state) => state.workspaceId);
  const networkId = useWorkspaceStore((state) => state.networkId);

  const [action, setAction] = useState("reroute_path");
  const [scopeJson, setScopeJson] = useState('{"building":"A","segment":"core"}');
  const [constraintsJson, setConstraintsJson] = useState('{"max_downtime":0}');
  const [intentId, setIntentId] = useUrlSelection("intent_id", session.urlScope);
  const [historyPage, setHistoryPage] = useState(1);
  const history = useIntentHistory(token, workspaceId, networkId, historyPage);
  const [validationAttempt, setValidationAttempt] = useState<ValidationAttempt | null>(null);
  // Used only for a legacy intent without a stored key; that key then becomes its identity.
  const [fallbackExecutionKey, setFallbackExecutionKey] = useState(() => randomId("intent-exec"));
  const [conflict, setConflict] = useState<IntentConflictGuidance | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [handoff, setHandoff] = useState<{ summary: string; untrusted: boolean } | null>(null);
  const [guided, setGuided] = useState(false);
  const [manualApproval, setManualApproval] = useState(false);
  const [simulationId, setSimulationId] = useState("");
  const simulationIdValid = !simulationId || /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(simulationId);
  const [executionRequest, setExecutionRequest] = useState<ExecuteIntentRequest | null>(null);
  const [executionNotice, setExecutionNotice] = useState<string | null>(null);
  const executionPending = useRef(false);
  const pushToast = useUiStore((state) => state.pushToast);
  const isNarrowViewport = useIsNarrowViewport();
  const appliedHandoffRef = useRef(false);

  const validateMutation = useValidateIntent(token);
  const executeMutation = useExecuteIntent(token);
  const detailQuery = useIntentDetail(token, intentId, workspaceId);
  const canExecute = canExecuteIntent(detailQuery.data);
  const permitted = hasPermission(profile, "write:config") && hasPermission(profile, "execute:rollback");
  const available = mode === "emulation" && permitted;
  const selectedDetail = !detailQuery.isError && detailQuery.data?.intent_id === intentId && detailQuery.data?.workspace_id === workspaceId && (!networkId || !detailQuery.data?.network_id || detailQuery.data.network_id === networkId);
  const labAction = detailQuery.data?.intent_payload?.action === "reroute_path" || detailQuery.data?.intent_payload?.action === "throttle_qos";
  const draft = JSON.stringify([action, scopeJson, constraintsJson]);
  const retryValidationKey = validationAttempt?.outcome === "unknown" && validationAttempt.draft === draft ? validationAttempt.key : null;
  const storedExecutionKey = selectedDetail ? detailQuery.data?.idempotency_key ?? null : null;
  const executionKey = executionRequest?.idempotency_key ?? storedExecutionKey ?? fallbackExecutionKey;

  /** Selecting another intent starts a new identity for both validation and execution (C3). */
  function selectIntent(next: string | null) {
    setIntentId(next);
    setManualApproval(false);
    setSimulationId("");
    setExecutionRequest(null);
    setExecutionNotice(null);
    setConflict(null);
    setValidationAttempt(null);
    setFallbackExecutionKey(randomId("intent-exec"));
  }

  const sceneObjects = useLiveStore((state) => state.sceneObjects);
  const sceneObjectIdsNewestFirst = useLiveStore((state) => state.sceneObjectIdsNewestFirst);
  const realtimeIntent = intentId ? sceneObjects[intentSceneObjectId(intentId)] : undefined;
  const intentRealtimeCards = useMemo(
    () =>
      sceneObjectIdsNewestFirst
        .map((id) => sceneObjects[id])
        .filter((item): item is (typeof sceneObjects)[string] => Boolean(item))
        .filter((item) => item.object_type === "intent_state")
        .slice(0, 20),
    [sceneObjects, sceneObjectIdsNewestFirst],
  );

  const lastRealtime = useRef<unknown>(null);
  const { refetch } = detailQuery;
  useEffect(() => {
    if (!intentId || !realtimeIntent || lastRealtime.current === realtimeIntent) {
      return;
    }
    const realtimeStatus = typeof realtimeIntent.status === "string" ? realtimeIntent.status : undefined;
    lastRealtime.current = realtimeIntent;
    if (!shouldRefetchIntentFromRealtime(undefined, realtimeStatus)) {
      return;
    }
    void refetch();
  }, [refetch, intentId, realtimeIntent]);

  useEffect(() => {
    setManualApproval(false);
  }, [available, session.authority, intentId]);

  async function validate(event: FormEvent) {
    event.preventDefault();
    if (!hasPermission(profile, "write:config") || executionPending.current || executionInFlight) return;
    setManualApproval(false);
    setValidationError(null);
    if (!workspaceId || !networkId) {
      pushToast({
        title: "Missing context",
        description: "Select a workspace and network before validating an intent.",
        tone: "warn",
      });
      return;
    }

    let scope: Record<string, unknown>;
    let constraints: Record<string, unknown>;
    try {
      scope = JSON.parse(scopeJson) as Record<string, unknown>;
      constraints = JSON.parse(constraintsJson) as Record<string, unknown>;
    } catch {
      setValidationError("Scope and constraints must be valid JSON objects.");
      return;
    }

    if (!scope || typeof scope !== "object" || Array.isArray(scope) || !constraints || typeof constraints !== "object" || Array.isArray(constraints)) {
      setValidationError("Scope and constraints must be JSON objects.");
      return;
    }

    // Fresh key per submission; only an unconfirmed submission of the same draft is retried with its key.
    const key = retryValidationKey ?? randomId("intent");
    setValidationAttempt({ key, draft, outcome: "pending" });
    setConflict(null);
    try {
      const response = await validateMutation.mutateAsync({
        request: {
          workspace_id: workspaceId,
          network_id: networkId,
          intent: {
            action,
            scope,
            constraints,
          },
        },
        idempotencyKey: key,
      });
      session.assertCurrent();
      selectIntent(response.intent_id);
      const coverage = response.validation?.validation_kind === "manual_lab_plan" ? "manual lab plan" : "schema-only validation";
      pushToast({
        title: response.idempotent_replay ? "Existing intent returned" : response.status === "validated" ? "Intent validated" : "Intent validation response",
        description: `Status: ${response.status} | ${coverage} | confidence ${response.confidence.band}${response.idempotent_replay ? " | replay of the same submission" : ""}`,
        tone: response.status === "validated" ? "ok" : "warn",
      });
    } catch (error) {
      try { session.assertCurrent(); } catch { return; }
      setValidationAttempt({ key, draft, outcome: isUnknownOutcome(error) ? "unknown" : "done" });
      setConflict(intentConflictGuidance(error));
      // The mutation error is rendered below; never leave a rejected form promise.
    }
  }

  async function execute(cancel = false) {
    // Browser back/forward must never apply an immutable retry to another intent.
    if (executionRequest && (executionRequest.intent_id !== intentId || executionRequest.workspace_id !== workspaceId)) return;
    if (!available || executionPending.current || !selectedDetail ||
      (!cancel && (terminalState || !manualApproval || !canExecute || !labAction || !simulationIdValid)) || (cancel && !canCancel)) return;
    if (!workspaceId || !intentId) {
      pushToast({
        title: "Nothing to execute",
        description: "Validate an intent first or provide an intent id.",
        tone: "warn",
      });
      return;
    }
    // Execute and cancel reuse the selected intent's stored key (C3) and echo its current approval binding.
    const approvalBinding = executionRequest?.approval_binding ?? detailQuery.data?.approval_binding ?? null;
    const request: ExecuteIntentRequest = {
      workspace_id: workspaceId,
      intent_id: intentId,
      idempotency_key: executionKey,
      manual_approval: cancel ? executionRequest?.manual_approval ?? manualApproval : true,
      cancel,
      ...(!cancel && (executionRequest?.simulation_id ?? simulationId) ? { simulation_id: executionRequest?.simulation_id ?? simulationId } : {}),
      ...(!cancel && approvalBinding ? { approval_binding: approvalBinding } : {}),
    };
    executionPending.current = true;
    setConflict(null);
    if (!cancel) setExecutionRequest(request);
    try {
      const response = await executeMutation.mutateAsync({
        request,
        idempotencyKey: request.idempotency_key,
      });
      session.assertCurrent();
      setExecutionNotice(response.status === "execution_started"
        ? cancel ? "Cancellation requested. Reconciliation or rollback must finish before a terminal outcome is known."
          : "Execution accepted, not completed. Waiting for authoritative readback."
        : "Execution response received. Consult the authoritative detail and verification below.");
      pushToast({
        title: response.status === "execution_failed" ? "Execution failed" : cancel ? "Cancellation requested" : response.idempotent_replay ? "Execution replayed" : "Execution request received",
        description: `Status: ${response.status} | Queue status: ${response.queue_status}${response.warning ? ` | ${response.warning}` : ""}`,
        tone: response.status === "execution_failed" ? "danger" : "warn",
      });
      await detailQuery.refetch();
    } catch (error) {
      try { session.assertCurrent(); } catch { return; }
      const guidance = intentConflictGuidance(error);
      if (guidance || !isUnknownOutcome(error)) {
        // Refused by the server: nothing ran, so the next attempt may change its inputs.
        if (!cancel) setExecutionRequest(null);
        if (!guidance || guidance.revokeApproval) setManualApproval(false);
        if (guidance?.refetchDetail) void detailQuery.refetch();
        setConflict(guidance);
        setExecutionNotice(guidance ? null : "The server refused the request; nothing was executed.");
        pushToast({ title: guidance?.title ?? "Execution request refused", description: guidance?.description ?? describeApiError(error), tone: "danger" });
        return;
      }
      setExecutionNotice("Request outcome unknown. A lost response does not mean the action did not run. Refresh detail or retry with the same identity.");
      void detailQuery.refetch();
      pushToast({
        title: "Execution request failed",
        description: toErrorMessage(error),
        tone: "danger",
      });
    } finally {
      executionPending.current = false;
    }
  }

  const terminalState = isIntentTerminalStatus(detailQuery.data?.status);
  const canCancel = Boolean(intentId && selectedDetail && canCancelIntent(detailQuery.data, Boolean(executionRequest)));
  const executionInFlight = !terminalState && (detailQuery.data?.status === "execution_started" || Boolean(executionRequest));

  useEffect(() => {
    if (appliedHandoffRef.current || typeof window === "undefined") {
      return;
    }
    const fromUrl = readUntrustedIntentQuery(window.location.search);
    if (fromUrl) {
      // Legacy links: strip the prefill from the address so it is not replayed or shared.
      const url = new URL(window.location.href);
      for (const name of HANDOFF_QUERY_PARAMS) url.searchParams.delete(name);
      window.history.replaceState(window.history.state, "", `${url.pathname}${url.search}${url.hash}`);
    }
    const prefill = routedHandoff ?? fromUrl;
    if (!prefill) {
      return;
    }
    appliedHandoffRef.current = true;
    if (prefill.action) setAction(prefill.action);
    if (prefill.scopeJson.trim()) setScopeJson(prefill.scopeJson);
    if (prefill.constraintsJson.trim()) setConstraintsJson(prefill.constraintsJson);
    setHandoff({ summary: prefill.contextSummary, untrusted: prefill.untrusted });
    if (!prefill.untrusted) onHandoffApplied();
  }, [routedHandoff, onHandoffApplied]);

  return (
    <div style={{ display: "grid", gap: "1rem" }}>
      <Panel title="Intent history" subtitle="Persisted intents in the selected workspace and network; selection never approves or executes">
        <Button tone="ghost" disabled={!workspaceId || history.isFetching} onClick={() => void history.refetch()}>Refresh intent history</Button>
        <QueryState query={history} hasData={(data) => data.items.length > 0} emptyTitle="No intent history" emptyDescription="No persisted intents on this page.">
          {(data) => <ul>{data.items.map((item) => <li key={item.intent_id}>
            <Button tone="ghost" disabled={executionInFlight || executeMutation.isPending || validateMutation.isPending} onClick={() => selectIntent(item.intent_id)}>{item.action ?? "Intent"} — {item.status}</Button>
            <span className="mono"> {item.intent_id} | {item.created_at}</span>
          </li>)}</ul>}
        </QueryState>
        <nav aria-label="Intent history pagination">
          <Button disabled={historyPage <= 1 || history.isFetching} onClick={() => setHistoryPage(historyPage - 1)}>Previous intents</Button>
          <span aria-live="polite"> Page {historyPage}{history.isPlaceholderData ? " (loading…)" : ""} | {history.data?.total ?? "Unknown"} intents </span>
          <Button disabled={!history.data || historyPage * history.data.page_size >= history.data.total || history.isFetching} onClick={() => setHistoryPage(historyPage + 1)}>Next intents</Button>
        </nav>
      </Panel>
      <Panel title="Intent Validate and Execute" subtitle="Define an outcome, review the evidence and validate before execution">
        {handoff ? (
          <div
            role={handoff.untrusted ? "alert" : "status"}
            style={{
              border: "1px solid var(--line-soft)",
              borderRadius: "9px",
              padding: "0.45rem 0.5rem",
              marginBottom: "0.7rem",
              color: "var(--ink-2)",
              fontSize: "0.85rem",
            }}
          >
            {handoff.untrusted
              ? <>Prefilled from a link (untrusted): the page address supplied these fields, not the Digital Twin view. Review every field before validating. Link summary (unverified): {handoff.summary || "none"}</>
              : <>Prefilled from Digital Twin: {handoff.summary || "no summary"}. Review every field before validating.</>}
          </div>
        ) : null}
        <form onSubmit={validate} style={{ display: "grid", gap: "0.7rem" }}>
          <label><input type="checkbox" checked={guided} disabled={validateMutation.isPending || executeMutation.isPending}
            onChange={(event) => {
              setGuided(event.target.checked);
              setManualApproval(false);
              if (event.target.checked) {
                setAction("reroute_path");
                setScopeJson('{"source_host":"h1","destination_host":"h2"}');
                setConstraintsJson('{"operation":"reroute","paths":[],"rate_mbps":null,"dscp":null}');
              }
            }} /> Guided manual lab action</label>
          {guided ? <LabActionFields onChange={(intent) => {
            setAction(intent.action);
            setScopeJson(JSON.stringify(intent.scope));
            setConstraintsJson(JSON.stringify(intent.constraints));
            setManualApproval(false);
          }} /> : <p>Advanced JSON validation remains available for other actions. Validation never grants manual approval.</p>}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: isNarrowViewport ? "1fr" : "1fr 1fr",
              gap: "0.7rem",
            }}
          >
            <label style={{ display: "grid", gap: "0.3rem" }}>
              <span className="mono" style={{ fontSize: "0.8rem", color: "var(--ink-3)" }}>
                Action
              </span>
              <select
                disabled={guided}
                value={action}
                onChange={(event) => { setAction(event.target.value); setManualApproval(false); }}
                style={{ border: "1px solid var(--line-soft)", borderRadius: "10px", padding: "0.45rem 0.5rem" }}
              >
                {INTENT_FORM_ACTIONS.map((value) => <option key={value} value={value}>{value}</option>)}
              </select>
            </label>

            <label style={{ display: "grid", gap: "0.3rem" }}>
              <span className="mono" style={{ fontSize: "0.8rem", color: "var(--ink-3)" }}>
                Execution idempotency key
              </span>
              <input
                readOnly
                aria-label="Execution idempotency key"
                value={selectedDetail ? executionKey : ""}
                placeholder={intentId ? "Loading the selected intent's stored key" : "Select or validate an intent"}
                style={{ border: "1px solid var(--line-soft)", borderRadius: "10px", padding: "0.45rem 0.5rem" }}
              />
              <span style={{ fontSize: "0.75rem", color: "var(--ink-3)" }}>
                {storedExecutionKey ? "The selected intent's stored key; execute and cancel always reuse it."
                  : selectedDetail ? "No stored key yet: this key becomes the intent's execution identity." : "Assigned by the selected intent."}
              </span>
            </label>
          </div>

          <label style={{ display: "grid", gap: "0.3rem" }}>
            <span className="mono" style={{ fontSize: "0.8rem", color: "var(--ink-3)" }}>
              Scope JSON
            </span>
            <textarea
              readOnly={guided}
              rows={4}
              value={scopeJson}
              onChange={(event) => { setScopeJson(event.target.value); setManualApproval(false); }}
              style={{ border: "1px solid var(--line-soft)", borderRadius: "10px", padding: "0.5rem", fontFamily: "var(--font-mono)" }}
            />
          </label>

          <label style={{ display: "grid", gap: "0.3rem" }}>
            <span className="mono" style={{ fontSize: "0.8rem", color: "var(--ink-3)" }}>
              Constraints JSON
            </span>
            <textarea
              readOnly={guided}
              rows={4}
              value={constraintsJson}
              onChange={(event) => { setConstraintsJson(event.target.value); setManualApproval(false); }}
              style={{ border: "1px solid var(--line-soft)", borderRadius: "10px", padding: "0.5rem", fontFamily: "var(--font-mono)" }}
            />
          </label>

          <p role="status">{mode !== "emulation"
            ? `Manual execution unavailable: ${mode ?? "unknown"} mode. Only authoritative EMULATION mode permits lab control; demo and production remain non-actuating.`
            : !permitted ? "Manual execution requires write:config and execute:rollback permissions."
              : "EMULATION only. Server opt-in, current authorization and trusted lab capabilities are still required."}</p>
          <label><input type="checkbox" checked={manualApproval}
            disabled={!available || !intentId || !selectedDetail || !labAction || terminalState || executeMutation.isPending || validateMutation.isPending}
            onChange={(event) => setManualApproval(event.target.checked)} />
            I explicitly approve this selected intent's manual lab execution (manual_approval=true)
          </label>
          <label style={{ display: "grid", gap: "0.3rem" }}>Referenced simulation UUID (optional)
            <input aria-label="Referenced simulation UUID" value={simulationId} aria-invalid={!simulationIdValid}
              disabled={Boolean(executionRequest) || executeMutation.isPending || executionInFlight || terminalState}
              onChange={(event) => { setSimulationId(event.target.value.trim()); setManualApproval(false); }} />
          </label>
          {!simulationIdValid && <p role="alert">Referenced simulation must be a UUID or empty.</p>}
          <p>An explicit simulation reference requires a prepared artifact bound to the exact intent, approved plan and current network-state hashes. Selecting an ID cannot synthesize those hashes or prepare evidence. No preparation endpoint is available here; the server rejects missing, mismatched, expired or failing evidence. Cancellation omits the simulation reference.</p>
          {selectedDetail && !labAction ? <p>This action is validation-only. Manual lab execution supports reroute_path and throttle_qos plans only.</p> : null}
          <p>Operator override is scoped to the selected manual lab policy: Cancel execution requests cancellation or compensation, not immediate rollback. Guided restore creates a separately approved restore plan. Neither control disables global safety gates or edits live PPO weights.</p>
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
            <Button permission="write:config" type="submit" disabled={validateMutation.isPending || executeMutation.isPending || executionInFlight}>
              {validateMutation.isPending ? "Validating..." : "Validate"}
            </Button>
            <Button
              permission="write:config"
              tone="ghost"
              type="button"
              disabled={!intentId || !selectedDetail || !labAction || !available || !manualApproval || !simulationIdValid || executeMutation.isPending || validateMutation.isPending || terminalState || !canExecute}
              onClick={() => void execute()}
            >
              {executeMutation.isPending ? "Executing..." : "Execute"}
            </Button>
            <Button permission="execute:rollback" tone="danger" type="button"
              disabled={!available || !canCancel || executeMutation.isPending}
              onClick={() => void execute(true)}>Cancel execution</Button>
            {canCancel && terminalState ? <p>Cancel requests compensation of the completed policy. The server checks current ownership; rollback is not confirmed until readback verifies it.</p> : null}
            <input
              aria-label="Intent ID"
              disabled={executeMutation.isPending || validateMutation.isPending || Boolean(executionRequest)}
              value={intentId ?? ""}
              onChange={(event) => selectIntent(event.target.value || null)}
              placeholder="Intent ID"
              style={{
                border: "1px solid var(--line-soft)",
                borderRadius: "10px",
                padding: "0.45rem 0.5rem",
                minWidth: isNarrowViewport ? 180 : 320,
                fontFamily: "var(--font-mono)",
              }}
              />
            </div>
          <p role="status" aria-label="Validation request key">
            {retryValidationKey
              ? `Validation outcome unknown: validating this unchanged draft again retries with key ${retryValidationKey}; the server returns the stored intent if it was recorded.`
              : "Each Validate submission uses a new request key."}
          </p>
          {executionNotice ? <p role="status">{executionNotice}</p> : null}
          {conflict ? <div role="alert"><strong>{conflict.title}</strong> ({conflict.code}): {conflict.description}</div> : null}
          {validationError ? <AsyncState title="Invalid request body" description={validationError} /> : null}
          {validateMutation.isError ? (
            <AsyncState title="Validation request failed" description={describeApiError(validateMutation.error)} />
          ) : null}
          {executeMutation.isError ? (
            <AsyncState title="Execution request failed" description={describeApiError(executeMutation.error)} />
          ) : null}
        </form>
      </Panel>

      <div style={{ display: "grid", gridTemplateColumns: isNarrowViewport ? "1fr" : "1fr 1fr", gap: "1rem", alignItems: "start" }}>
        <Panel title="Intent Detail" subtitle="Evidence, execution history and lifecycle for the selected intent">
          {intentId ? <div style={{ marginBottom: "0.7rem" }}>
            <p>Detail polling backs off to 15 seconds and stops after 40 reads or a terminal result. Realtime reconnects also reconcile detail. A deadline or connection loss is not proof of cancellation.</p>
            <Button tone="ghost" disabled={detailQuery.isFetching} onClick={() => void detailQuery.refetch()}>Refresh execution status</Button>
          </div> : null}
          <QueryState
            query={detailQuery}
            emptyTitle="No intent selected"
            emptyDescription="Validate an intent first or paste intent id."
          >
            {(detail) => {
              const lifecycle = mapIntentLifecycle(detail);
              const diagnostics = mapExecutionDiagnostics(detail);
              const uncertain = detail.execution_provenance.uncertain === true || detail.execution_provenance.phase === "uncertain" || diagnostics.verificationStatus === "uncertain" || diagnostics.rollbackStatus === "failed" || diagnostics.rollbackStatus === "unverified";
              return (
                <div style={{ display: "grid", gap: "0.56rem" }}>
                  <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap" }}>
                    <Badge text={statusLabel(detail.status)} tone={intentStatusTone(detail.status)} />
                    <Badge text={`confidence ${detail.confidence.band}`} tone={intentConfidenceBandTone(detail.confidence.band)} />
                    <Badge text={statusLabel(detail.queue_status)} tone={intentQueueStatusTone(detail.queue_status)} />
                  </div>
                  <div style={{ color: "var(--ink-2)", fontSize: "0.9rem" }}>{explainabilitySummary(detail)}</div>
                  <ValidationDisclosure detail={detail} />
                  <ApprovalBindingSummary detail={detail} labAction={detail.intent_payload?.action === "reroute_path" || detail.intent_payload?.action === "throttle_qos"} />
                  {detail.status === "execution_started" ? <p role="status">Execution in progress, not completed. Awaiting verification and reconciliation.</p> : null}
                  {uncertain ? <AsyncState title="Execution outcome uncertain" description="Do not assume changes were undone. Reconciliation and verified rollback are required before further lab mutations." /> : null}
                  {diagnostics.noMutationVerified ? <p role="status">No mutation verified by the backend. This is not successful execution or rollback.</p> : null}
                  <details>
                    <summary>Selected intent payload (approval applies to this plan)</summary>
                    <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{JSON.stringify(detail.intent_payload, null, 2)}</pre>
                  </details>
                  <div aria-label="Execution provenance" style={{ overflowWrap: "anywhere" }}>
                    <PathEvidencePanel detail={detail} />
                    {(["execution_id", "phase", "deadline"] as const).map((field) => (
                      <div key={field} className="mono">{field}: {typeof detail.execution_provenance[field] === "string" ? String(detail.execution_provenance[field]) : "Not reported"}</div>
                    ))}
                    <p>Completion requires actual readback, not queue acceptance. Missing verification or rollback evidence remains unknown.</p>
                    <div className="mono">completion_scope: {diagnostics.completionScope ?? "Not reported"}</div>
                    <p>Configuration readback and reachability do not establish workload performance improvement.</p>
                    {diagnostics.readbackSha256 ? <div className="mono">readback_sha256: {diagnostics.readbackSha256}</div> : null}
                    {diagnostics.probeSummary ? <div>Reachability probe: {diagnostics.probeSummary}</div> : null}
                    {diagnostics.rollbackReadbackSha256 ? <div className="mono">rollback.readback_sha256: {diagnostics.rollbackReadbackSha256}</div> : null}
                    <details>
                      <summary>Execution provenance, verification and rollback evidence</summary>
                      <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{JSON.stringify(detail.execution_provenance, null, 2)}</pre>
                    </details>
                  </div>

                  <div style={{ display: "flex", gap: "0.35rem", flexWrap: "wrap" }}>
                    {diagnostics.verificationStatus ? (
                      <Badge
                        text={`verification ${diagnostics.verificationStatus}`}
                        tone={diagnostics.verificationStatus === "passed" || diagnostics.verificationStatus === "readback verified" ? "ok" : "warn"}
                      />
                    ) : null}
                    {diagnostics.rollbackAttempted || diagnostics.rollbackStatus ? (
                      <Badge
                        text={`rollback ${diagnostics.rollbackStatus ?? "attempted"}`}
                        tone={diagnostics.rollbackStatus === "completed" || diagnostics.rollbackStatus === "verified" ? "ok" : "danger"}
                      />
                    ) : null}
                    {diagnostics.eventPublicationWarning ? (
                      <Badge text={`event ${diagnostics.eventPublicationWarning}`} tone="warn" />
                    ) : null}
                  </div>
                  {diagnostics.rollbackReferenceId ? (
                    <div className="mono" style={{ color: "var(--ink-3)", fontSize: "0.74rem" }}>
                      rollback_ref: {diagnostics.rollbackReferenceId}
                    </div>
                  ) : null}
                  {diagnostics.failureReason ? (
                    <div className="mono" style={{ color: "var(--ink-3)", fontSize: "0.74rem" }}>
                      failure_reason: {diagnostics.failureReason}
                    </div>
                  ) : null}
                  {diagnostics.failureReason ? (
                    <AsyncState title="Execution failed" description={diagnostics.failureReason} />
                  ) : null}

                  <div style={{ display: "grid", gap: "0.36rem" }}>
                    {lifecycle.map((item) => (
                      <div
                        key={item.key}
                        style={{
                          border: "1px solid var(--line-soft)",
                          borderRadius: "9px",
                          padding: "0.42rem 0.48rem",
                          display: "flex",
                          justifyContent: "space-between",
                        }}
                      >
                        <span>{item.label}</span>
                        <span style={{ color: "var(--ink-3)", fontSize: "0.8rem" }}>
                          {item.timestamp ? formatTimestamp(item.timestamp) : item.status}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              );
            }}
          </QueryState>
        </Panel>

        <Panel title="Realtime Intent Deltas" subtitle="Incoming intent lifecycle updates from the digital twin stream">
          <SceneReconciliationStatus />
          {intentRealtimeCards.length === 0 ? (
            <div style={{ color: "var(--ink-3)" }}>No intent realtime deltas observed yet.</div>
          ) : (
            <div style={{ display: "grid", gap: "0.4rem", maxHeight: 360, overflow: "auto" }}>
              {intentRealtimeCards.map((item) => {
                const changedFields = item.changed_fields;
                const verificationStatus =
                  changedFields && typeof changedFields === "object" && "verification_status" in changedFields
                    ? displayValue((changedFields as { verification_status?: unknown }).verification_status, "").trim()
                    : "";
                const rollbackStatus =
                  changedFields && typeof changedFields === "object" && "rollback_status" in changedFields
                    ? displayValue((changedFields as { rollback_status?: unknown }).rollback_status, "").trim()
                    : "";

                return (
                  <div
                    key={`${item.id}-${String(item.status)}`}
                    style={{ border: "1px solid var(--line-soft)", borderRadius: "9px", padding: "0.44rem 0.48rem" }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between" }}>
                      <strong>{item.id}</strong>
                      <Badge text={statusLabel(item.status)} tone={intentStatusTone(item.status)} />
                    </div>
                    {verificationStatus || rollbackStatus ? (
                      <div style={{ display: "flex", gap: "0.35rem", marginTop: "0.2rem" }}>
                        {verificationStatus ? <Badge text={`verification ${verificationStatus}`} tone="warn" /> : null}
                        {rollbackStatus ? (
                          <Badge text={`rollback ${rollbackStatus}`} tone={rollbackStatus === "completed" ? "ok" : "danger"} />
                        ) : null}
                      </div>
                    ) : null}
                    <div className="mono" style={{ color: "var(--ink-3)", fontSize: "0.74rem" }}>
                      intent_id: {String(item.intent_id ?? "-")}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </Panel>
      </div>
    </div>
  );
}

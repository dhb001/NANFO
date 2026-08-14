import { FormEvent, useEffect, useMemo, useState } from "react";
import { useExecuteIntent, useIntentDetail, useValidateIntent } from "@/features/intent/hooks";
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
  resolveConfidenceTone,
  shouldRefetchIntentFromRealtime,
} from "@/features/intent/logic";
import { formatTimestamp } from "@/shared/lib/format";
import { useLiveStore } from "@/features/realtime/store";
import { AsyncState } from "@/shared/ui/AsyncState";
import { useUiStore } from "@/shared/state/ui-store";
import { ApiClientError, toErrorMessage } from "@/shared/lib/errors";
import { useIsNarrowViewport } from "@/shared/lib/viewport";
import { canExecuteIntent, normalizeIntentStatus } from "@/shared/lib/intent";

export function IntentPage() {
  const token = useAuthStore((state) => state.accessToken);
  const workspaceId = useWorkspaceStore((state) => state.workspaceId);
  const networkId = useWorkspaceStore((state) => state.networkId);

  const [action, setAction] = useState("reroute_path");
  const [scopeJson, setScopeJson] = useState('{"building":"A","segment":"core"}');
  const [constraintsJson, setConstraintsJson] = useState('{"max_downtime":0}');
  const [intentId, setIntentId] = useState<string | null>(null);
  const [idempotencyKey, setIdempotencyKey] = useState(`intent-${Date.now()}`);
  const [validationError, setValidationError] = useState<string | null>(null);
  const pushToast = useUiStore((state) => state.pushToast);
  const isNarrowViewport = useIsNarrowViewport();

  const validateMutation = useValidateIntent(token);
  const executeMutation = useExecuteIntent(token);
  const detailQuery = useIntentDetail(token, intentId, workspaceId);
  const canExecute = canExecuteIntent(detailQuery.data);

  const sceneObjects = useLiveStore((state) => state.sceneObjects);
  const realtimeIntent = intentId ? sceneObjects[intentSceneObjectId(intentId)] : undefined;
  const intentRealtimeCards = useMemo(
    () => Object.values(sceneObjects).filter((item) => item.object_type === "intent_state").slice(0, 20),
    [sceneObjects],
  );

  useEffect(() => {
    if (!intentId || !detailQuery.data || !realtimeIntent) {
      return;
    }
    const realtimeStatus = typeof realtimeIntent.status === "string" ? realtimeIntent.status : undefined;
    if (!shouldRefetchIntentFromRealtime(detailQuery.data.status, realtimeStatus)) {
      return;
    }
    detailQuery.refetch();
  }, [detailQuery, intentId, realtimeIntent]);

  async function validate(event: FormEvent) {
    event.preventDefault();
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

    if (!scope || Array.isArray(scope) || !constraints || Array.isArray(constraints)) {
      setValidationError("Scope and constraints must be JSON objects.");
      return;
    }

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
      idempotencyKey,
    });
    setIntentId(response.intent_id);
    pushToast({
      title: "Intent validated",
      description: `Status: ${response.status} | confidence ${response.confidence.band}`,
      tone: response.status === "validated" ? "ok" : "warn",
    });
  }

  async function execute() {
    if (!workspaceId || !intentId) {
      pushToast({
        title: "Nothing to execute",
        description: "Validate an intent first or provide an intent id.",
        tone: "warn",
      });
      return;
    }
    try {
      const response = await executeMutation.mutateAsync({
        request: {
          workspace_id: workspaceId,
          intent_id: intentId,
          idempotency_key: idempotencyKey,
        },
        idempotencyKey,
      });
      pushToast({
        title: response.idempotent_replay ? "Execution replayed" : "Execution accepted",
        description: `Queue status: ${response.queue_status}`,
        tone: response.queue_status === "queued" ? "ok" : "warn",
      });
      await detailQuery.refetch();
    } catch (error) {
      if (error instanceof ApiClientError && error.code === "INTENT_IDEMPOTENCY_CONFLICT") {
        pushToast({
          title: "Idempotency conflict",
          description: "This key is bound to another intent. Use a new idempotency key.",
          tone: "danger",
        });
        return;
      }
      pushToast({
        title: "Execution failed",
        description: toErrorMessage(error),
        tone: "danger",
      });
    }
  }

  const terminalState = isIntentTerminalStatus(detailQuery.data?.status);

  return (
    <div style={{ display: "grid", gap: "1rem" }}>
      <Panel title="Intent Validate and Execute" subtitle="VS8 explainability, confidence, lifecycle transitions">
        <form onSubmit={validate} style={{ display: "grid", gap: "0.7rem" }}>
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
                value={action}
                onChange={(event) => setAction(event.target.value)}
                style={{ border: "1px solid var(--line-soft)", borderRadius: "10px", padding: "0.45rem 0.5rem" }}
              >
                <option value="reroute_path">reroute_path</option>
                <option value="isolate_vlan">isolate_vlan</option>
                <option value="optimize_wireless_capacity">optimize_wireless_capacity</option>
                <option value="throttle_qos">throttle_qos</option>
              </select>
            </label>

            <label style={{ display: "grid", gap: "0.3rem" }}>
              <span className="mono" style={{ fontSize: "0.8rem", color: "var(--ink-3)" }}>
                Idempotency Key
              </span>
              <input
                value={idempotencyKey}
                onChange={(event) => setIdempotencyKey(event.target.value)}
                style={{ border: "1px solid var(--line-soft)", borderRadius: "10px", padding: "0.45rem 0.5rem" }}
              />
            </label>
          </div>

          <label style={{ display: "grid", gap: "0.3rem" }}>
            <span className="mono" style={{ fontSize: "0.8rem", color: "var(--ink-3)" }}>
              Scope JSON
            </span>
            <textarea
              rows={4}
              value={scopeJson}
              onChange={(event) => setScopeJson(event.target.value)}
              style={{ border: "1px solid var(--line-soft)", borderRadius: "10px", padding: "0.5rem", fontFamily: "var(--font-mono)" }}
            />
          </label>

          <label style={{ display: "grid", gap: "0.3rem" }}>
            <span className="mono" style={{ fontSize: "0.8rem", color: "var(--ink-3)" }}>
              Constraints JSON
            </span>
            <textarea
              rows={4}
              value={constraintsJson}
              onChange={(event) => setConstraintsJson(event.target.value)}
              style={{ border: "1px solid var(--line-soft)", borderRadius: "10px", padding: "0.5rem", fontFamily: "var(--font-mono)" }}
            />
          </label>

          <div style={{ display: "flex", gap: "0.5rem" }}>
            <Button type="submit" disabled={validateMutation.isPending}>
              {validateMutation.isPending ? "Validating..." : "Validate"}
            </Button>
            <Button
              tone="ghost"
              type="button"
              disabled={!intentId || executeMutation.isPending || terminalState || !canExecute}
              onClick={execute}
            >
              {executeMutation.isPending ? "Executing..." : "Execute"}
            </Button>
            <input
              value={intentId ?? ""}
              onChange={(event) => setIntentId(event.target.value || null)}
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
          {validationError ? <AsyncState title="Invalid request body" description={validationError} /> : null}
          {validateMutation.isError ? (
            <AsyncState title="Validation request failed" description={toErrorMessage(validateMutation.error)} />
          ) : null}
          {executeMutation.isError ? (
            <AsyncState title="Execution request failed" description={toErrorMessage(executeMutation.error)} />
          ) : null}
        </form>
      </Panel>

      <div style={{ display: "grid", gridTemplateColumns: isNarrowViewport ? "1fr" : "1fr 1fr", gap: "1rem", alignItems: "start" }}>
        <Panel title="Intent Detail" subtitle="GET /intents/{id} + lifecycle timeline">
          <QueryState
            query={detailQuery}
            emptyTitle="No intent selected"
            emptyDescription="Validate an intent first or paste intent id."
          >
            {(detail) => {
              const lifecycle = mapIntentLifecycle(detail);
              const diagnostics = mapExecutionDiagnostics(detail);
              return (
                <div style={{ display: "grid", gap: "0.56rem" }}>
                  <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap" }}>
                    <Badge
                      text={normalizeIntentStatus(detail.status)}
                      tone={detail.status === "execution_failed" ? "danger" : detail.status === "execution_completed" ? "ok" : "warn"}
                    />
                    <Badge text={`confidence ${detail.confidence.band}`} tone={resolveConfidenceTone(detail.confidence.score)} />
                    <Badge text={detail.queue_status} tone={detail.queue_status === "queued" ? "ok" : "warn"} />
                  </div>
                  <div style={{ color: "var(--ink-2)", fontSize: "0.9rem" }}>{explainabilitySummary(detail)}</div>

                  <div style={{ display: "flex", gap: "0.35rem", flexWrap: "wrap" }}>
                    {diagnostics.verificationStatus ? (
                      <Badge
                        text={`verification ${diagnostics.verificationStatus}`}
                        tone={diagnostics.verificationStatus === "passed" ? "ok" : "warn"}
                      />
                    ) : null}
                    {diagnostics.rollbackAttempted ? (
                      <Badge
                        text={`rollback ${diagnostics.rollbackStatus ?? "attempted"}`}
                        tone={diagnostics.rollbackStatus === "completed" ? "ok" : "danger"}
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

        <Panel title="Realtime Intent Deltas" subtitle="/ws/digital-twin intent.* mapped scene_object updates">
          {intentRealtimeCards.length === 0 ? (
            <div style={{ color: "var(--ink-3)" }}>No intent realtime deltas observed yet.</div>
          ) : (
            <div style={{ display: "grid", gap: "0.4rem", maxHeight: 360, overflow: "auto" }}>
              {intentRealtimeCards.map((item) => {
                const changedFields = item.changed_fields;
                const verificationStatus =
                  changedFields && typeof changedFields === "object" && "verification_status" in changedFields
                    ? String((changedFields as { verification_status?: unknown }).verification_status ?? "").trim()
                    : "";
                const rollbackStatus =
                  changedFields && typeof changedFields === "object" && "rollback_status" in changedFields
                    ? String((changedFields as { rollback_status?: unknown }).rollback_status ?? "").trim()
                    : "";

                return (
                  <div
                    key={`${item.id}-${String(item.status)}`}
                    style={{ border: "1px solid var(--line-soft)", borderRadius: "9px", padding: "0.44rem 0.48rem" }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between" }}>
                      <strong>{item.id}</strong>
                      <Badge
                        text={String(item.status ?? "unknown")}
                        tone={
                          item.status === "execution_failed"
                            ? "danger"
                            : item.status === "execution_completed" || item.status === "validated"
                              ? "ok"
                              : "warn"
                        }
                      />
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

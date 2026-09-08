import { FormEvent, useMemo, useState } from "react";

import { useGenerateReport, useReportDetail } from "@/features/reporting/hooks";
import {
  inferReportErrorMessage,
  isReportTerminal,
  mapQueueTone,
  mapReportStatusTone,
  summarizeArtifactKinds,
} from "@/features/reporting/logic";
import { ApiClientError, toErrorMessage } from "@/shared/lib/errors";
import { formatNumber, formatTimestamp } from "@/shared/lib/format";
import { randomId } from "@/shared/lib/uid";
import { useIsNarrowViewport } from "@/shared/lib/viewport";
import { useAuthStore } from "@/shared/state/auth-store";
import { useUiStore } from "@/shared/state/ui-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { AsyncState } from "@/shared/ui/AsyncState";
import { Badge } from "@/shared/ui/Badge";
import { Button } from "@/shared/ui/Button";
import { Panel } from "@/shared/ui/Panel";
import { QueryState } from "@/shared/ui/QueryState";

function parseJsonObject(value: string, label: string): Record<string, unknown> {
  const parsed = JSON.parse(value) as unknown;
  if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
    throw new Error(`${label} must be a JSON object.`);
  }
  return parsed as Record<string, unknown>;
}

export function ReportsPage() {
  const token = useAuthStore((state) => state.accessToken);
  const workspaceId = useWorkspaceStore((state) => state.workspaceId);
  const networkId = useWorkspaceStore((state) => state.networkId);
  const pushToast = useUiStore((state) => state.pushToast);
  const isNarrowViewport = useIsNarrowViewport();

  const [reportType, setReportType] = useState("executive_summary");
  const [outputFormat, setOutputFormat] = useState<"pdf" | "csv">("pdf");
  const [startAt, setStartAt] = useState("2026-08-01T00:00:00Z");
  const [endAt, setEndAt] = useState("2026-08-14T00:00:00Z");
  const [scopeJson, setScopeJson] = useState('{"workspace":"all"}');
  const [filtersJson, setFiltersJson] = useState('{"kpi":"latency"}');
  const [idempotencyKey, setIdempotencyKey] = useState(randomId("report"));
  const [reportId, setReportId] = useState<string | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);

  const generateMutation = useGenerateReport(token);
  const reportQuery = useReportDetail(token, reportId, workspaceId);

  const detail = reportQuery.data ?? null;
  const reportErrorMessage = inferReportErrorMessage(detail);
  const isFailed = detail?.status === "failed";

  const artifactSummary = useMemo(() => {
    if (!detail) {
      return "none";
    }
    return summarizeArtifactKinds(detail.artifacts);
  }, [detail]);

  async function submitGenerate(options?: { regenerateIdempotencyKey?: boolean }) {
    setValidationError(null);
    if (!workspaceId) {
      pushToast({
        title: "Workspace required",
        description: "Select an active workspace before requesting reports.",
        tone: "warn",
      });
      return;
    }

    let scope: Record<string, unknown>;
    let filters: Record<string, unknown>;
    try {
      scope = parseJsonObject(scopeJson, "Scope JSON");
      filters = parseJsonObject(filtersJson, "Filters JSON");
    } catch (error) {
      setValidationError(error instanceof Error ? error.message : "Scope/filters JSON is invalid.");
      return;
    }

    const normalizedReportType = reportType.trim();
    if (!normalizedReportType) {
      setValidationError("Report type is required.");
      return;
    }

    const startDate = new Date(startAt);
    const endDate = new Date(endAt);
    if (Number.isNaN(startDate.getTime()) || Number.isNaN(endDate.getTime()) || startDate.getTime() > endDate.getTime()) {
      setValidationError("Date range must include valid timestamps where start is before or equal to end.");
      return;
    }

    const effectiveIdempotencyKey = options?.regenerateIdempotencyKey
      ? randomId("report")
      : idempotencyKey.trim() || randomId("report");

    setIdempotencyKey(effectiveIdempotencyKey);

    try {
      const result = await generateMutation.mutateAsync({
        request: {
          workspace_id: workspaceId,
          network_id: networkId,
          report_type: normalizedReportType,
          format: outputFormat,
          date_range: {
            start: startDate.toISOString(),
            end: endDate.toISOString(),
          },
          scope,
          filters,
        },
        idempotencyKey: effectiveIdempotencyKey,
      });

      setReportId(result.report_id);
      pushToast({
        title: result.status === "failed" ? "Report failed: no artifacts generated" : result.idempotent_replay ? "Report replayed" : "Report request accepted",
        description: `Status ${result.status} | queue ${result.queue_status}`,
        tone: result.status === "failed" ? "danger" : mapQueueTone(result.queue_status) === "warn" ? "warn" : "ok",
      });
    } catch (error) {
      if (error instanceof ApiClientError && error.code === "REPORT_IDEMPOTENCY_CONFLICT") {
        pushToast({
          title: "Idempotency conflict",
          description: "This key is bound to a different report request. A new key was generated.",
          tone: "warn",
        });
        setIdempotencyKey(randomId("report"));
        return;
      }

      pushToast({
        title: "Report request failed",
        description: toErrorMessage(error),
        tone: "danger",
      });
    }
  }

  async function onGenerateSubmit(event: FormEvent) {
    event.preventDefault();
    await submitGenerate();
  }

  return (
    <div style={{ display: "grid", gap: "1rem" }}>
      <Panel title="Report Generator" subtitle="VS13 async reporting baseline for queued generation and status tracking">
        <form onSubmit={onGenerateSubmit} style={{ display: "grid", gap: "0.65rem" }}>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: isNarrowViewport ? "1fr" : "repeat(4, minmax(0, 1fr))",
              gap: "0.55rem",
            }}
          >
            <label style={{ display: "grid", gap: "0.3rem" }}>
              <span className="mono" style={{ fontSize: "0.78rem", color: "var(--ink-3)" }}>
                Report Type
              </span>
              <input
                aria-label="Report Type"
                value={reportType}
                onChange={(event) => setReportType(event.target.value)}
                style={{ border: "1px solid var(--line-soft)", borderRadius: "10px", padding: "0.45rem 0.5rem" }}
              />
            </label>

            <label style={{ display: "grid", gap: "0.3rem" }}>
              <span className="mono" style={{ fontSize: "0.78rem", color: "var(--ink-3)" }}>
                Output Format
              </span>
              <select
                aria-label="Output Format"
                value={outputFormat}
                onChange={(event) => setOutputFormat(event.target.value === "csv" ? "csv" : "pdf")}
                style={{ border: "1px solid var(--line-soft)", borderRadius: "10px", padding: "0.45rem 0.5rem" }}
              >
                <option value="pdf">pdf</option>
                <option value="csv">csv</option>
              </select>
            </label>

            <label style={{ display: "grid", gap: "0.3rem" }}>
              <span className="mono" style={{ fontSize: "0.78rem", color: "var(--ink-3)" }}>
                Date Range Start
              </span>
              <input
                aria-label="Date Range Start"
                value={startAt}
                onChange={(event) => setStartAt(event.target.value)}
                style={{ border: "1px solid var(--line-soft)", borderRadius: "10px", padding: "0.45rem 0.5rem" }}
              />
            </label>

            <label style={{ display: "grid", gap: "0.3rem" }}>
              <span className="mono" style={{ fontSize: "0.78rem", color: "var(--ink-3)" }}>
                Date Range End
              </span>
              <input
                aria-label="Date Range End"
                value={endAt}
                onChange={(event) => setEndAt(event.target.value)}
                style={{ border: "1px solid var(--line-soft)", borderRadius: "10px", padding: "0.45rem 0.5rem" }}
              />
            </label>
          </div>

          <label style={{ display: "grid", gap: "0.3rem" }}>
            <span className="mono" style={{ fontSize: "0.78rem", color: "var(--ink-3)" }}>
              Scope JSON
            </span>
            <textarea
              aria-label="Scope JSON"
              rows={3}
              value={scopeJson}
              onChange={(event) => setScopeJson(event.target.value)}
              style={{ border: "1px solid var(--line-soft)", borderRadius: "10px", padding: "0.45rem 0.5rem", fontFamily: "var(--font-mono)" }}
            />
          </label>

          <label style={{ display: "grid", gap: "0.3rem" }}>
            <span className="mono" style={{ fontSize: "0.78rem", color: "var(--ink-3)" }}>
              Filters JSON
            </span>
            <textarea
              aria-label="Filters JSON"
              rows={3}
              value={filtersJson}
              onChange={(event) => setFiltersJson(event.target.value)}
              style={{ border: "1px solid var(--line-soft)", borderRadius: "10px", padding: "0.45rem 0.5rem", fontFamily: "var(--font-mono)" }}
            />
          </label>

          <label style={{ display: "grid", gap: "0.3rem" }}>
            <span className="mono" style={{ fontSize: "0.78rem", color: "var(--ink-3)" }}>
              Idempotency Key
            </span>
            <input
              aria-label="Idempotency Key"
              value={idempotencyKey}
              onChange={(event) => setIdempotencyKey(event.target.value)}
              style={{ border: "1px solid var(--line-soft)", borderRadius: "10px", padding: "0.45rem 0.5rem", fontFamily: "var(--font-mono)" }}
            />
          </label>

          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
            <Button permission="read:telemetry" type="submit" disabled={generateMutation.isPending}>
              {generateMutation.isPending ? "Requesting..." : "Generate Report"}
            </Button>
            {reportId ? <Badge text={`report ${reportId.slice(0, 8)}`} tone="info" /> : null}
          </div>

          {validationError ? <AsyncState title="Invalid report request" description={validationError} /> : null}
          {generateMutation.isError ? (
            <AsyncState title="Report request failed" description={toErrorMessage(generateMutation.error)} />
          ) : null}
        </form>
      </Panel>

      <Panel title="Report Status" subtitle="Auto-refreshing lifecycle with artifact metadata and failure diagnostics">
        <QueryState
          query={reportQuery}
          emptyTitle="No report selected"
          emptyDescription="Generate a report to inspect queued, terminal, and artifact states."
        >
          {(report) => (
            <div style={{ display: "grid", gap: "0.65rem" }}>
              <div style={{ display: "flex", gap: "0.35rem", flexWrap: "wrap" }}>
                <Badge text={`status ${report.status}`} tone={mapReportStatusTone(report.status)} />
                <Badge text={`queue ${report.queue_status}`} tone={mapQueueTone(report.queue_status)} />
                <Badge text={`format ${report.format}`} tone="info" />
                <Badge text={`artifacts ${report.artifacts.length}`} tone={report.artifacts.length > 0 ? "ok" : "warn"} />
              </div>

              <div style={{ display: "grid", gap: "0.22rem" }}>
                <div className="mono" style={{ color: "var(--ink-3)", fontSize: "0.75rem" }}>
                  report_id: {report.report_id}
                </div>
                <div className="mono" style={{ color: "var(--ink-3)", fontSize: "0.75rem" }}>
                  requested_at: {formatTimestamp(report.requested_at)}
                </div>
                <div className="mono" style={{ color: "var(--ink-3)", fontSize: "0.75rem" }}>
                  completed_at: {formatTimestamp(report.completed_at)}
                </div>
                <div className="mono" style={{ color: "var(--ink-3)", fontSize: "0.75rem" }}>
                  artifact_types: {artifactSummary}
                </div>
                {report.warning ? (
                  <div className="mono" style={{ color: "var(--warn)", fontSize: "0.75rem" }}>
                    warning: {report.warning}
                  </div>
                ) : null}
              </div>

              {reportErrorMessage ? (
                <AsyncState
                  title="Report generation failed"
                  description={reportErrorMessage}
                  action={
                    <Button
                      type="button"
                      tone="danger"
                      onClick={() => submitGenerate({ regenerateIdempotencyKey: true })}
                      disabled={generateMutation.isPending}
                    >
                      Retry Failed Report
                    </Button>
                  }
                />
              ) : null}

              {!report.artifacts.length ? (
                <AsyncState
                  title={isReportTerminal(report.status) ? "No artifacts generated" : "Artifacts pending"}
                  description={
                    isReportTerminal(report.status)
                      ? "This report reached a terminal state without artifact references."
                      : "Artifact references appear when report generation reaches a terminal state."
                  }
                />
              ) : (
                <div style={{ display: "grid", gap: "0.45rem" }}>
                  {report.artifacts.map((artifact) => (
                    <article
                      key={artifact.artifact_id}
                      style={{
                        border: "1px solid var(--line-soft)",
                        borderRadius: "10px",
                        padding: "0.55rem 0.6rem",
                        display: "grid",
                        gap: "0.28rem",
                      }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", gap: "0.45rem", alignItems: "center", flexWrap: "wrap" }}>
                        <strong>{artifact.artifact_id}</strong>
                        <Badge text={artifact.media_type} tone="ok" />
                      </div>
                      <div className="mono" style={{ color: "var(--ink-3)", fontSize: "0.74rem", wordBreak: "break-all" }}>
                        {artifact.uri}
                      </div>
                      <div style={{ display: "flex", gap: "0.35rem", flexWrap: "wrap" }}>
                        <Badge text={`${formatNumber(artifact.size_bytes, 0)} bytes`} tone="info" />
                        <Badge text={`sha256 ${artifact.checksum_sha256.slice(0, 12)}...`} tone="neutral" />
                      </div>
                    </article>
                  ))}
                </div>
              )}

              {isFailed && !reportErrorMessage ? (
                <Button
                  type="button"
                  tone="danger"
                  onClick={() => submitGenerate({ regenerateIdempotencyKey: true })}
                  disabled={generateMutation.isPending}
                >
                  Retry Failed Report
                </Button>
              ) : null}
            </div>
          )}
        </QueryState>
      </Panel>
    </div>
  );
}

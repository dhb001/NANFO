import { FormEvent, useState } from "react";
import { hasPermission } from "@/features/auth/permissions";
import { useGenerateReport, useReportDetail, useReportHistory } from "./hooks";
import { ReportDownload } from "./ReportDownload";
import { hasGeneratedArtifact, inferReportErrorMessage, mapQueueTone, mapReportStatusTone } from "./logic";
import { ApiClientError, describeApiError } from "@/shared/lib/errors";
import { displayValue, formatTimestamp } from "@/shared/lib/format";
import { randomId } from "@/shared/lib/uid";
import { useAuthStore } from "@/shared/state/auth-store";
import { useUiStore } from "@/shared/state/ui-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { GenerateReportRequest } from "@/shared/types/reporting";
import { AsyncState } from "@/shared/ui/AsyncState";
import { Badge } from "@/shared/ui/Badge";
import { Button } from "@/shared/ui/Button";
import { Panel } from "@/shared/ui/Panel";
import { QueryState } from "@/shared/ui/QueryState";

export function ReportsPage() {
  const workspaceId = useWorkspaceStore((state) => state.workspaceId);
  const networkId = useWorkspaceStore((state) => state.networkId);
  const generation = useAuthStore((state) => state.generation);
  return <ReportWorkspace key={`${generation}:${workspaceId}:${networkId}`} workspaceId={workspaceId} networkId={networkId} />;
}

function ReportWorkspace({ workspaceId, networkId }: { workspaceId: string | null; networkId: string | null }) {
  const token = useAuthStore((state) => state.accessToken);
  const canGenerate = useAuthStore((state) => hasPermission(state.profile, "write:config") && hasPermission(state.profile, "read:telemetry"));
  const pushToast = useUiStore((state) => state.pushToast);
  const [type, setType] = useState<GenerateReportRequest["report_type"]>("executive_summary");
  const [format, setFormat] = useState<"pdf" | "csv">("pdf");
  const [start, setStart] = useState(() => new Date(Date.now() - 86400_000).toISOString());
  const [end, setEnd] = useState(() => new Date().toISOString());
  const [scope, setScope] = useState<GenerateReportRequest["scope"]>({});
  const [filters, setFilters] = useState<GenerateReportRequest["filters"]>({ max_rows: 100 });
  const [idempotencyKey, setIdempotencyKey] = useState(() => randomId("report"));
  const [reportId, setReportId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const generate = useGenerateReport(token);
  const detail = useReportDetail(token, reportId, workspaceId);
  const history = useReportHistory(token, workspaceId, page);
  const summary = type === "executive_summary" || type === "operational_summary";

  async function submit(event?: FormEvent) {
    event?.preventDefault();
    if (!canGenerate || generate.isPending) return;
    setError(null);
    if (!workspaceId) { setError("Select a workspace before requesting a report."); return; }
    const from = Date.parse(start), to = Date.parse(end);
    if (!Number.isFinite(from) || !Number.isFinite(to) || from >= to) {
      setError("Provide valid timestamps with start before end (exclusive)."); return;
    }
    try {
      const result = await generate.mutateAsync({ request: {
        workspace_id: workspaceId, network_id: networkId, report_type: type, format,
        date_range: { start: new Date(from).toISOString(), end: new Date(to).toISOString() }, scope, filters,
      }, idempotencyKey });
      setReportId(result.report_id);
      pushToast({ title: result.status === "failed" ? "Report failed: no artifacts generated" : hasGeneratedArtifact(result) ? "Generated artifact available" : "Report request accepted",
        description: `Status ${result.status} | queue ${result.queue_status}`, tone: result.status === "failed" ? "danger" : "info" });
    } catch (cause) {
      setError(describeApiError(cause));
      if (cause instanceof ApiClientError && cause.code === "REPORT_IDEMPOTENCY_CONFLICT") setIdempotencyKey(randomId("report"));
    }
  }

  return <div style={{ display: "grid", gap: "1rem", minWidth: 0 }}>
    <Panel title="Report Generator" subtitle="Backend-validated fields. Last 24 hours by default; exclusive end, maximum 31 days.">
      <form onSubmit={submit} style={{ display: "grid", gap: "0.65rem" }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 220px), 1fr))", gap: "0.55rem" }}>
          <label>Report Type<select aria-label="Report Type" value={type} onChange={(event) => { setType(event.target.value as typeof type); setScope({}); setFilters({ max_rows: 100 }); }}>
            {["executive_summary", "operational_summary", "telemetry", "alerts", "simulation", "intent"].map((value) => <option key={value}>{value}</option>)}
          </select></label>
          <label>Output Format<select aria-label="Output Format" value={format} onChange={(event) => setFormat(event.target.value as typeof format)}><option>pdf</option><option>csv</option></select></label>
          <label>Date Range Start<input aria-label="Date Range Start" required value={start} onChange={(event) => setStart(event.target.value)} /></label>
          <label>Date Range End<input aria-label="Date Range End" required value={end} onChange={(event) => setEnd(event.target.value)} /></label>
          <label>Maximum Rows<input aria-label="Maximum Rows" type="number" min={1} max={500} required value={filters.max_rows ?? 100} onChange={(event) => setFilters({ ...filters, max_rows: event.target.valueAsNumber })} /></label>
          {summary || type === "telemetry" ? <label>Metric<input aria-label="Metric" maxLength={100} value={filters.metric ?? ""} onChange={(event) => setFilters({ ...filters, metric: event.target.value || null })} /></label> : null}
          {summary || type === "alerts" ? <>
            <label>Alert Status<select aria-label="Alert Status" value={filters.alert_status ?? ""} onChange={(event) => setFilters({ ...filters, alert_status: event.target.value as typeof filters.alert_status || null })}>
              <option value="">All</option>{["active", "acknowledged", "resolved"].map((value) => <option key={value}>{value}</option>)}
            </select></label>
            <label>Alert Severity<select aria-label="Alert Severity" value={filters.alert_severity ?? ""} onChange={(event) => setFilters({ ...filters, alert_severity: event.target.value as typeof filters.alert_severity || null })}>
              <option value="">All</option>{["info", "warning", "critical", "low", "medium", "high"].map((value) => <option key={value}>{value}</option>)}
            </select></label>
          </> : null}
          {(["simulation", "intent"] as const).map((source) => summary || type === source ? <label key={source}>{source} IDs (up to 20, comma-separated)
            <input aria-label={`${source} IDs`} value={scope[`${source}_ids`]?.join(",") ?? ""} onChange={(event) => setScope({ ...scope, [`${source}_ids`]: event.target.value ? event.target.value.split(",").map((id) => id.trim()) : [] })} />
          </label> : null)}
        </div>
        <p>Workspace: {workspaceId ?? "not selected"}; network: {networkId ?? "all authorized networks"}. Missing data and truncation are explicit.</p>
        <label>Idempotency Key<input aria-label="Idempotency Key" required value={idempotencyKey} onChange={(event) => setIdempotencyKey(event.target.value)} /></label>
        <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
          <Button permission="write:config" type="submit" disabled={!canGenerate || !workspaceId || generate.isPending}>{generate.isPending ? "Requesting..." : "Generate Report"}</Button>
          <Button tone="ghost" type="button" onClick={() => setIdempotencyKey(randomId("report"))}>New Request Key</Button>
        </div>
        {error ? <AsyncState title="Report request failed" description={error} /> : null}
      </form>
    </Panel>
    <Panel title="Report History">
      <QueryState query={history} hasData={(data) => data.items.length > 0} emptyTitle="No report history">
        {(data) => <div style={{ display: "grid", gap: "0.4rem" }}>{data.items.map((report) => <Button tone="ghost" key={report.report_id} onClick={() => setReportId(report.report_id)}>
          {report.report_type} / {report.format} / {report.status === "generated" && !hasGeneratedArtifact(report) ? "artifact unavailable" : report.status} / {formatTimestamp(report.requested_at)} / network {report.network_id ?? "all"}
        </Button>)}</div>}
      </QueryState>
      <nav aria-label="Report history pages" style={{ display: "flex", gap: "0.5rem", alignItems: "center", flexWrap: "wrap" }}>
        <Button tone="ghost" disabled={page <= 1 || history.isFetching} onClick={() => setPage(page - 1)}>Previous Reports</Button>
        <span>Page {page}{history.data ? `; ${history.data.total} reports` : ""}</span>
        <Button tone="ghost" disabled={!history.data || history.isFetching || page * history.data.page_size >= history.data.total} onClick={() => setPage(page + 1)}>Next Reports</Button>
        <Button tone="ghost" onClick={() => history.refetch()}>Refresh History</Button>
      </nav>
    </Panel>
    <Panel title="Report Status">
      <QueryState query={detail} emptyTitle="No report selected" emptyDescription="Generate a report or select a history entry.">
        {(report) => <div style={{ display: "grid", gap: "0.6rem", overflowWrap: "anywhere" }}>
          <div style={{ display: "flex", gap: "0.35rem", flexWrap: "wrap" }}>
            <Badge text={report.status === "generated" && !hasGeneratedArtifact(report) ? "Artifact unavailable / unverified" : `status ${report.status}`} tone={report.status === "generated" && !hasGeneratedArtifact(report) ? "warn" : mapReportStatusTone(report.status)} />
            <Badge text={`queue ${report.queue_status}`} tone={mapQueueTone(report.queue_status)} />
          </div>
          <span>Report {report.report_id}</span><span>Requested {formatTimestamp(report.requested_at)}; completed {formatTimestamp(report.completed_at)}</span>
          {report.warning ? <p>Warning: {report.warning}</p> : null}
          {report.snapshot_summary && Object.entries(report.snapshot_summary).map(([name, raw]) => {
            if (!["telemetry", "alerts", "simulation", "intent"].includes(name) || !raw || typeof raw !== "object") return null;
            const section = raw as Record<string, unknown>;
            return <p key={name}>{name}: {typeof section.row_count === "number" ? section.row_count : "unavailable"} rows; total {typeof section.total === "number" ? section.total : "unknown"}; {section.truncated === true ? "truncated" : "not truncated"}; time field {displayValue(section.time_field)}; omissions: {Array.isArray(section.omissions) ? section.omissions.filter((item) => typeof item === "string").join(", ") || "none" : "unavailable"}</p>;
          })}
          {inferReportErrorMessage(report) ? <AsyncState title="Report generation failed" description={inferReportErrorMessage(report) ?? undefined} /> : null}
          {!hasGeneratedArtifact(report) ? <AsyncState title={report.status === "requested" ? "Artifacts pending" : "No verified artifacts available"} /> : <>
            <span>Artifact version {report.artifact_version}; snapshot SHA-256 {report.snapshot_sha256}</span>
            <ReportDownload key={`${report.report_id}:${report.status_version}:${report.snapshot_sha256}`} report={report} />
          </>}
          {report.status === "failed" ? <Button permission="write:config" disabled={!canGenerate || generate.isPending} onClick={() => { setIdempotencyKey(randomId("report")); setError("Review the current form, then Generate Report with the new key."); }}>Retry Failed Report</Button> : null}
          <Button tone="ghost" onClick={() => detail.refetch()}>Refresh Report Status</Button>
        </div>}
      </QueryState>
    </Panel>
  </div>;
}

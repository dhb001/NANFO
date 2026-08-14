import { ReportRecord } from "@/shared/types/reporting";

const TERMINAL_REPORT_STATUSES = new Set(["generated", "failed"]);

export function normalizeReportStatus(status: string | null | undefined): string {
  const normalized = String(status ?? "").trim().toLowerCase();
  if (!normalized) {
    return "unknown";
  }
  return normalized;
}

export function isReportTerminal(status: string | null | undefined): boolean {
  return TERMINAL_REPORT_STATUSES.has(normalizeReportStatus(status));
}

export function mapReportStatusTone(status: string | null | undefined): "ok" | "warn" | "danger" | "info" {
  const normalized = normalizeReportStatus(status);
  if (normalized === "generated") {
    return "ok";
  }
  if (normalized === "failed") {
    return "danger";
  }
  if (normalized === "requested") {
    return "info";
  }
  return "warn";
}

export function mapQueueTone(queueStatus: string | null | undefined): "ok" | "warn" | "info" {
  const normalized = String(queueStatus ?? "").trim().toLowerCase();
  if (normalized === "queued" || normalized === "replayed") {
    return "ok";
  }
  if (normalized === "deferred") {
    return "warn";
  }
  return "info";
}

export function inferReportErrorMessage(report: ReportRecord | null | undefined): string | null {
  if (!report || !report.error) {
    return null;
  }
  const message = String(report.error.message ?? "").trim();
  if (message) {
    return message;
  }
  const code = String(report.error.code ?? "").trim();
  return code || "Report generation failed.";
}

export function summarizeArtifactKinds(artifacts: ReportRecord["artifacts"]): string {
  if (!artifacts.length) {
    return "none";
  }
  const formats = new Set<string>();
  for (const artifact of artifacts) {
    const parts = artifact.media_type.split("/");
    const label = parts[1] ?? parts[0] ?? "artifact";
    formats.add(label);
  }
  return Array.from(formats).sort().join(", ");
}

import { ReportRecord } from "@/shared/types/reporting";
import { reportQueueStatusTone, reportStatusTone, type StatusTone } from "@/shared/lib/statusTones";

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

/** Explicit backend `reports.status` map; unknown values are neutral (ADR-028). */
export function mapReportStatusTone(status: string | null | undefined): StatusTone {
  return reportStatusTone(status);
}

/** Explicit backend `reports.queue_status` map; unknown values are neutral (ADR-028). */
export function mapQueueTone(queueStatus: string | null | undefined): StatusTone {
  return reportQueueStatusTone(queueStatus);
}

export function inferReportErrorMessage(report: ReportRecord | null | undefined): string | null {
  return report?.error ? report.error.message?.trim() || report.error.code?.trim() || "Report generation failed." : null;
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

export function hasGeneratedArtifact(report: ReportRecord): boolean {
  return report.status === "generated" && report.artifact_version === 1 && (report.status_version ?? 0) >= 2
    && /^[a-f0-9]{64}$/i.test(report.snapshot_sha256 ?? "") && report.artifacts.length > 0
    && report.artifacts.every((artifact) => /^[a-f0-9]{64}$/i.test(artifact.checksum_sha256)
      && Number.isSafeInteger(artifact.size_bytes) && artifact.size_bytes > 0
      && ["application/pdf", "text/csv"].includes(artifact.media_type));
}

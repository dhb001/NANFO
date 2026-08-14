import { LiveAlertItem } from "@/features/realtime/store";

const severityRanking: Record<string, number> = {
  critical: 5,
  high: 4,
  degraded: 3,
  medium: 2,
  low: 1,
  info: 0,
};

export function alertSeverityWeight(alert: LiveAlertItem): number {
  const payloadSeverity = String(alert.payload.severity ?? "").toLowerCase();
  return severityRanking[payloadSeverity] ?? 0;
}

export function summarizeAlertSource(alerts: LiveAlertItem[]): Record<string, number> {
  return alerts.reduce<Record<string, number>>((acc, alert) => {
    const source = alert.source || "unknown";
    acc[source] = (acc[source] ?? 0) + 1;
    return acc;
  }, {});
}

export function isResolvedAlert(alert: LiveAlertItem): boolean {
  return alert.event_type === "alert.resolved";
}

export function isAcknowledgedAlert(alert: LiveAlertItem): boolean {
  return alert.event_type === "alert.acknowledged";
}

export function normalizeAlertStatus(status: string): string {
  const normalized = status.trim().toLowerCase();
  if (normalized === "ack") {
    return "acknowledged";
  }
  return normalized;
}

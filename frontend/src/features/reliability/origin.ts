import { AlertRecord } from "@/shared/types/alerts";

function nestedScope(alert: AlertRecord): Record<string, unknown> {
  const nested = alert.payload.scope;
  return nested && typeof nested === "object" && !Array.isArray(nested) ? nested as Record<string, unknown> : {};
}

export function alertOrigin(alert: AlertRecord): string {
  const scope = nestedScope(alert);
  const value = (key: string) => {
    const item = alert.payload[key] ?? scope[key];
    return typeof item === "string" ? item : "not recorded";
  };
  return `Origin: source ${alert.source}; organization ${value("org_id")}; workspace ${value("workspace_id")}; network ${value("network_id")}`;
}

/**
 * Platform-scoped (runtime SLO) alert: top-level `alert_scope: "platform"` and no recorded
 * workspace (backend alert/scope.py is_platform_scoped). Only global Admins can read these
 * and nobody can acknowledge/resolve them: the SLO evaluator owns their lifecycle.
 */
export function isPlatformAlert(alert: AlertRecord): boolean {
  const workspace = alert.payload.workspace_id ?? nestedScope(alert).workspace_id;
  return alert.payload.alert_scope === "platform" && (workspace === undefined || workspace === null);
}

export interface EvaluationWindow {
  start: string | null;
  end: string | null;
  seconds: number | null;
  counterReset: boolean | null;
}

/** The SLO evaluation window recorded on a platform alert, or null when absent/malformed. */
export function evaluationWindow(payload: Record<string, unknown>): EvaluationWindow | null {
  const raw = payload.evaluation_window;
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const window = raw as Record<string, unknown>;
  const text = (value: unknown) => typeof value === "string" && value ? value : null;
  return {
    start: text(window.start),
    end: text(window.end),
    seconds: typeof window.seconds === "number" && Number.isFinite(window.seconds) ? window.seconds : null,
    counterReset: typeof window.counter_reset === "boolean" ? window.counter_reset : null,
  };
}

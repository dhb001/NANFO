import { AlertRecord } from "@/shared/types/alerts";

export function alertOrigin(alert: AlertRecord): string {
  const nested = alert.payload.scope;
  const scope = nested && typeof nested === "object" ? nested as Record<string, unknown> : {};
  const value = (key: string) => {
    const item = alert.payload[key] ?? scope[key];
    return typeof item === "string" ? item : "not recorded";
  };
  return `Origin: source ${alert.source}; organization ${value("org_id")}; workspace ${value("workspace_id")}; network ${value("network_id")}`;
}

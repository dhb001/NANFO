import { apiRequest } from "@/shared/lib/api";
import {
  InstallPluginRequest,
  PluginActionResult,
  PluginListResult,
} from "@/shared/types/plugins";

interface ListPluginsParams {
  status?: "installed" | "enabled" | "disabled" | "failed";
  enabled?: boolean;
  search?: string;
  limit?: number;
}

function buildListPluginsQuery(params: ListPluginsParams): string {
  const query = new URLSearchParams();
  if (params.status) {
    query.set("status", params.status);
  }
  if (typeof params.enabled === "boolean") {
    query.set("enabled", String(params.enabled));
  }
  if (params.search) {
    query.set("search", params.search);
  }
  query.set("limit", String(params.limit ?? 200));
  return query.toString();
}

export function listPlugins(token: string, params: ListPluginsParams = {}) {
  const query = buildListPluginsQuery(params);
  const path = query ? `/api/v1/plugins?${query}` : "/api/v1/plugins";
  return apiRequest<PluginListResult>(path, { token });
}

export function installPlugin(token: string, body: InstallPluginRequest) {
  return apiRequest<PluginActionResult>("/api/v1/plugins/install", {
    method: "POST",
    body,
    token,
  });
}

export function enablePlugin(token: string, pluginId: string) {
  return apiRequest<PluginActionResult>(`/api/v1/plugins/${pluginId}/enable`, {
    method: "POST",
    token,
  });
}

export function disablePlugin(token: string, pluginId: string) {
  return apiRequest<PluginActionResult>(`/api/v1/plugins/${pluginId}/disable`, {
    method: "POST",
    token,
  });
}

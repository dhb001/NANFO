import { apiRequest, apiRequestNoContent } from "@/shared/lib/api";
import type {
  InstallPluginRequest,
  PluginActionResult,
  PluginListResult,
  PluginStatus,
} from "@/shared/types/plugins";

interface ListPluginsParams {
  status?: PluginStatus | undefined;
  enabled?: boolean | undefined;
  search?: string | undefined;
  limit?: number | undefined;
}

function buildListPluginsQuery(params: ListPluginsParams): string {
  const query = new URLSearchParams();
  for (const key of ["status", "enabled", "search"] as const) {
    if (params[key] !== undefined) query.set(key, String(params[key]));
  }
  query.set("limit", String(params.limit ?? 200));
  return query.toString();
}

export function listPlugins(token: string, params: ListPluginsParams = {}, signal?: AbortSignal) {
  const query = buildListPluginsQuery(params);
  const path = query ? `/api/v1/plugins?${query}` : "/api/v1/plugins";
  return apiRequest<PluginListResult>(path, { token, signal });
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

export function uninstallPlugin(token: string, pluginId: string) {
  return apiRequestNoContent(`/api/v1/plugins/${encodeURIComponent(pluginId)}`, { token });
}

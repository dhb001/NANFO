import { PluginRecord } from "@/shared/types/plugins";

export interface PluginStatusSummary {
  installed: number;
  enabled: number;
  disabled: number;
  failed: number;
}

export function normalizePluginStatus(status: string): string {
  return status.trim().toLowerCase();
}

export function isPluginSafeToEnable(plugin: PluginRecord): boolean {
  return (
    normalizePluginStatus(plugin.signature_status) === "verified"
    && normalizePluginStatus(plugin.dependency_status) === "compatible"
    && normalizePluginStatus(plugin.sandbox_status) === "isolated"
  );
}

export function pluginStatusSummary(plugins: PluginRecord[]): PluginStatusSummary {
  const summary: PluginStatusSummary = {
    installed: 0,
    enabled: 0,
    disabled: 0,
    failed: 0,
  };
  for (const plugin of plugins) {
    const status = normalizePluginStatus(plugin.status);
    if (status === "installed") {
      summary.installed += 1;
      continue;
    }
    if (status === "enabled") {
      summary.enabled += 1;
      continue;
    }
    if (status === "disabled") {
      summary.disabled += 1;
      continue;
    }
    if (status === "failed") {
      summary.failed += 1;
    }
  }
  return summary;
}

export function pluginSafetyTone(plugin: PluginRecord): "ok" | "warn" | "danger" {
  if (normalizePluginStatus(plugin.status) === "failed") {
    return "danger";
  }
  if (isPluginSafeToEnable(plugin)) {
    return "ok";
  }
  return "warn";
}

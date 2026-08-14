import { describe, expect, it } from "vitest";

import {
  isPluginSafeToEnable,
  normalizePluginStatus,
  pluginSafetyTone,
  pluginStatusSummary,
} from "@/shared/lib/plugins";
import { PluginRecord } from "@/shared/types/plugins";

function makePlugin(overrides: Partial<PluginRecord> = {}): PluginRecord {
  return {
    plugin_id: "00000000-0000-0000-0000-000000000701",
    plugin_key: "safe-plugin",
    name: "Safe Plugin",
    version: "1.0.0",
    manifest: {
      plugin_key: "safe-plugin",
      name: "Safe Plugin",
      version: "1.0.0",
      signer: "nanfo-labs",
      signature: "sig:abcdef1234567890",
      dependencies: {
        platform_version: "0.1.0",
        requires: ["core:telemetry"],
      },
      sandbox: {
        isolation_mode: "process",
        permissions: ["read:telemetry"],
      },
      metadata: {},
    },
    signature_status: "verified",
    dependency_status: "compatible",
    sandbox_status: "isolated",
    status: "installed",
    enabled: false,
    failure_reason: null,
    queue_status: "queued",
    stream_entry_id: "701-0",
    warning: null,
    installed_at: "2026-08-14T12:00:00Z",
    updated_at: "2026-08-14T12:00:00Z",
    ...overrides,
  };
}

describe("plugins helpers", () => {
  it("normalizes plugin status", () => {
    expect(normalizePluginStatus(" ENABLED ")).toBe("enabled");
  });

  it("computes safety eligibility", () => {
    expect(isPluginSafeToEnable(makePlugin())).toBe(true);
    expect(isPluginSafeToEnable(makePlugin({ signature_status: "invalid" }))).toBe(false);
    expect(isPluginSafeToEnable(makePlugin({ dependency_status: "incompatible" }))).toBe(false);
    expect(isPluginSafeToEnable(makePlugin({ sandbox_status: "blocked" }))).toBe(false);
  });

  it("summarizes status counts", () => {
    const summary = pluginStatusSummary([
      makePlugin({ status: "installed" }),
      makePlugin({ plugin_id: "2", status: "enabled" }),
      makePlugin({ plugin_id: "3", status: "disabled" }),
      makePlugin({ plugin_id: "4", status: "failed" }),
    ]);
    expect(summary).toEqual({ installed: 1, enabled: 1, disabled: 1, failed: 1 });
  });

  it("maps plugin safety tone", () => {
    expect(pluginSafetyTone(makePlugin())).toBe("ok");
    expect(pluginSafetyTone(makePlugin({ status: "failed" }))).toBe("danger");
    expect(pluginSafetyTone(makePlugin({ dependency_status: "incompatible" }))).toBe("warn");
  });
});

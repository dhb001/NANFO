import { FormEvent, useState } from "react";

import {
  useDisablePlugin,
  useEnablePlugin,
  useInstallPlugin,
  usePluginsQuery,
} from "@/features/plugins/hooks";
import { ApiClientError, toErrorMessage } from "@/shared/lib/errors";
import {
  isPluginSafeToEnable,
  normalizePluginStatus,
  pluginSafetyTone,
  pluginStatusSummary,
} from "@/shared/lib/plugins";
import { useAuthStore } from "@/shared/state/auth-store";
import { useUiStore } from "@/shared/state/ui-store";
import { Badge } from "@/shared/ui/Badge";
import { Button } from "@/shared/ui/Button";
import { Panel } from "@/shared/ui/Panel";
import { QueryState } from "@/shared/ui/QueryState";

type PluginStatusFilter = "all" | "installed" | "enabled" | "disabled" | "failed";

const ALLOWED_PLUGIN_PERMISSIONS = new Set([
  "read:telemetry",
  "read:topology",
  "read:alerts",
]);

export function PluginsPage() {
  const token = useAuthStore((state) => state.accessToken);
  const pushToast = useUiStore((state) => state.pushToast);

  const [pluginKey, setPluginKey] = useState("safe-plugin");
  const [name, setName] = useState("Safe Plugin");
  const [version, setVersion] = useState("1.0.0");
  const [signer, setSigner] = useState("nanfo-labs");
  const [signature, setSignature] = useState("sig:abcdef1234567890");
  const [requires, setRequires] = useState("core:telemetry");
  const [permissionsText, setPermissionsText] = useState("read:telemetry, read:topology");
  const [statusFilter, setStatusFilter] = useState<PluginStatusFilter>("all");
  const [searchText, setSearchText] = useState("");
  const [pendingPluginId, setPendingPluginId] = useState<string | null>(null);

  const pluginsQuery = usePluginsQuery(token, {
    status: statusFilter === "all" ? undefined : statusFilter,
    search: searchText.trim() || undefined,
    limit: 200,
    pollMs: 4000,
  });
  const installMutation = useInstallPlugin(token);
  const enableMutation = useEnablePlugin(token);
  const disableMutation = useDisablePlugin(token);

  const plugins = pluginsQuery.data?.items ?? [];
  const summary = pluginStatusSummary(plugins);

  async function handleInstall(event: FormEvent) {
    event.preventDefault();
    try {
      const requiresList = requires
        .split(",")
        .map((entry) => entry.trim())
        .filter(Boolean);
      const requestedPermissions = permissionsText
        .split(",")
        .map((entry) => entry.trim())
        .filter(Boolean);
      const normalizedPermissions = requestedPermissions.map((permission) => permission.toLowerCase());
      const invalidPermission = normalizedPermissions.find(
        (permission) => !ALLOWED_PLUGIN_PERMISSIONS.has(permission),
      );
      if (invalidPermission) {
        pushToast({
          title: "Invalid permission",
          description: `Unsupported permission: ${invalidPermission}`,
          tone: "warn",
        });
        return;
      }

      const result = await installMutation.mutateAsync({
        plugin_key: pluginKey.trim(),
        name: name.trim(),
        version: version.trim(),
        signer: signer.trim(),
        signature: signature.trim(),
        dependencies: {
          platform_version: "0.1.0",
          requires: requiresList,
        },
        sandbox: {
          isolation_mode: "process",
          permissions: normalizedPermissions,
        },
        metadata: {
          category: "connector",
        },
      });
      pushToast({
        title: result.idempotent_replay ? "Plugin already installed" : "Plugin installed",
        description: `Queue status: ${result.queue_status}`,
        tone: result.queue_status === "queued" || result.queue_status === "replayed" ? "ok" : "warn",
      });
      await pluginsQuery.refetch();
    } catch (error) {
      pushToast({
        title: "Install failed",
        description: toErrorMessage(error),
        tone: "danger",
      });
    }
  }

  async function handleEnable(pluginId: string) {
    try {
      setPendingPluginId(pluginId);
      const result = await enableMutation.mutateAsync(pluginId);
      pushToast({
        title: result.idempotent_replay ? "Plugin already enabled" : "Plugin enabled",
        description: `Queue status: ${result.queue_status}`,
        tone: result.queue_status === "queued" || result.queue_status === "replayed" ? "ok" : "warn",
      });
      await pluginsQuery.refetch();
    } catch (error) {
      if (
        error instanceof ApiClientError
        && (
          error.code === "PLUGIN_DEPENDENCY_INCOMPATIBLE"
          || error.code === "PLUGIN_SIGNATURE_INVALID"
          || error.code === "PLUGIN_PERMISSION_SCOPE_INVALID"
          || error.code === "PLUGIN_SANDBOX_INVALID"
        )
      ) {
        await pluginsQuery.refetch();
        pushToast({
          title: "Plugin blocked by safety checks",
          description: error.message,
          tone: "warn",
        });
      } else {
        pushToast({
          title: "Enable failed",
          description: toErrorMessage(error),
          tone: "danger",
        });
      }
    } finally {
      setPendingPluginId(null);
    }
  }

  async function handleDisable(pluginId: string) {
    try {
      setPendingPluginId(pluginId);
      const result = await disableMutation.mutateAsync(pluginId);
      pushToast({
        title: result.idempotent_replay ? "Plugin already disabled" : "Plugin disabled",
        description: `Queue status: ${result.queue_status}`,
        tone: result.queue_status === "queued" || result.queue_status === "replayed" ? "ok" : "warn",
      });
      await pluginsQuery.refetch();
    } catch (error) {
      pushToast({
        title: "Disable failed",
        description: toErrorMessage(error),
        tone: "danger",
      });
    } finally {
      setPendingPluginId(null);
    }
  }

  return (
    <div style={{ display: "grid", gap: "1rem" }}>
      <Panel title="Plugin Runtime Safety" subtitle="VS12 plugin registry lifecycle with signature, dependency, and sandbox safety checks">
        <form onSubmit={handleInstall} style={{ display: "grid", gap: "0.65rem" }}>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: "0.55rem" }}>
            <label style={{ display: "grid", gap: "0.3rem" }}>
              <span className="mono" style={{ fontSize: "0.78rem", color: "var(--ink-3)" }}>Plugin Key</span>
              <input
                value={pluginKey}
                onChange={(event) => setPluginKey(event.target.value)}
                aria-label="Plugin Key"
                style={{ border: "1px solid var(--line-soft)", borderRadius: "10px", padding: "0.45rem 0.5rem" }}
              />
            </label>
            <label style={{ display: "grid", gap: "0.3rem" }}>
              <span className="mono" style={{ fontSize: "0.78rem", color: "var(--ink-3)" }}>Name</span>
              <input
                value={name}
                onChange={(event) => setName(event.target.value)}
                aria-label="Name"
                style={{ border: "1px solid var(--line-soft)", borderRadius: "10px", padding: "0.45rem 0.5rem" }}
              />
            </label>
            <label style={{ display: "grid", gap: "0.3rem" }}>
              <span className="mono" style={{ fontSize: "0.78rem", color: "var(--ink-3)" }}>Version</span>
              <input
                value={version}
                onChange={(event) => setVersion(event.target.value)}
                aria-label="Version"
                style={{ border: "1px solid var(--line-soft)", borderRadius: "10px", padding: "0.45rem 0.5rem" }}
              />
            </label>
            <label style={{ display: "grid", gap: "0.3rem" }}>
              <span className="mono" style={{ fontSize: "0.78rem", color: "var(--ink-3)" }}>Signer</span>
              <input
                value={signer}
                onChange={(event) => setSigner(event.target.value)}
                aria-label="Signer"
                style={{ border: "1px solid var(--line-soft)", borderRadius: "10px", padding: "0.45rem 0.5rem" }}
              />
            </label>
          </div>

          <label style={{ display: "grid", gap: "0.3rem" }}>
            <span className="mono" style={{ fontSize: "0.78rem", color: "var(--ink-3)" }}>Signature</span>
            <input
              value={signature}
              onChange={(event) => setSignature(event.target.value)}
              aria-label="Signature"
              style={{ border: "1px solid var(--line-soft)", borderRadius: "10px", padding: "0.45rem 0.5rem", fontFamily: "var(--font-mono)" }}
            />
          </label>

          <label style={{ display: "grid", gap: "0.3rem" }}>
            <span className="mono" style={{ fontSize: "0.78rem", color: "var(--ink-3)" }}>Dependencies (comma-separated)</span>
            <input
              value={requires}
              onChange={(event) => setRequires(event.target.value)}
              aria-label="Dependencies (comma-separated)"
              style={{ border: "1px solid var(--line-soft)", borderRadius: "10px", padding: "0.45rem 0.5rem" }}
            />
          </label>

          <label style={{ display: "grid", gap: "0.3rem" }}>
            <span className="mono" style={{ fontSize: "0.78rem", color: "var(--ink-3)" }}>Sandbox Permissions (comma-separated)</span>
            <input
              value={permissionsText}
              onChange={(event) => setPermissionsText(event.target.value)}
              aria-label="Sandbox permissions"
              style={{ border: "1px solid var(--line-soft)", borderRadius: "10px", padding: "0.45rem 0.5rem" }}
            />
            <span className="mono" style={{ fontSize: "0.72rem", color: "var(--ink-3)" }}>
              Allowed: read:telemetry, read:topology, read:alerts
            </span>
          </label>

          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
            <Button type="submit" disabled={installMutation.isPending}>
              {installMutation.isPending ? "Installing..." : "Install Plugin"}
            </Button>
            <Badge text={`installed ${summary.installed}`} tone="info" />
            <Badge text={`enabled ${summary.enabled}`} tone="ok" />
            <Badge text={`disabled ${summary.disabled}`} tone="warn" />
            <Badge text={`failed ${summary.failed}`} tone={summary.failed > 0 ? "danger" : "info"} />
          </div>
        </form>
      </Panel>

      <Panel
        title="Plugin Registry"
        subtitle="Install, enable, disable lifecycle controls with safety-state messaging"
        action={(
          <div style={{ display: "flex", gap: "0.4rem", alignItems: "center", flexWrap: "wrap" }}>
            <input
              value={searchText}
              onChange={(event) => setSearchText(event.target.value)}
              aria-label="Filter plugins"
              placeholder="Search plugins"
              style={{ border: "1px solid var(--line-soft)", borderRadius: "8px", padding: "0.32rem 0.4rem" }}
            />
            <Button tone={statusFilter === "all" ? "primary" : "ghost"} onClick={() => setStatusFilter("all")}>All</Button>
            <Button tone={statusFilter === "installed" ? "primary" : "ghost"} onClick={() => setStatusFilter("installed")}>Installed</Button>
            <Button tone={statusFilter === "enabled" ? "primary" : "ghost"} onClick={() => setStatusFilter("enabled")}>Enabled</Button>
            <Button tone={statusFilter === "disabled" ? "primary" : "ghost"} onClick={() => setStatusFilter("disabled")}>Disabled</Button>
            <Button tone={statusFilter === "failed" ? "primary" : "ghost"} onClick={() => setStatusFilter("failed")}>Failed</Button>
          </div>
        )}
      >
        <QueryState
          query={pluginsQuery}
          hasData={(data) => data.items.length > 0}
          emptyTitle="No plugins in registry"
          emptyDescription="Install a plugin to start lifecycle verification and controls."
        >
          {(data) => (
            <div style={{ display: "grid", gap: "0.45rem", maxHeight: 540, overflow: "auto" }}>
              {data.items.map((plugin) => {
                const normalizedStatus = normalizePluginStatus(plugin.status);
                const safetyReady = isPluginSafeToEnable(plugin);
                const actionLoading = pendingPluginId === plugin.plugin_id;
                const canEnable = !plugin.enabled && normalizedStatus !== "failed" && safetyReady;
                const canDisable = plugin.enabled;

                return (
                  <article
                    key={plugin.plugin_id}
                    style={{
                      border: "1px solid var(--line-soft)",
                      borderRadius: "10px",
                      padding: "0.55rem 0.6rem",
                      background:
                        normalizedStatus === "failed"
                          ? "color-mix(in srgb, var(--danger) 7%, white)"
                          : plugin.enabled
                            ? "color-mix(in srgb, var(--ok) 6%, white)"
                            : "white",
                      display: "grid",
                      gap: "0.35rem",
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "0.5rem", flexWrap: "wrap" }}>
                      <strong>{plugin.name}</strong>
                      <div style={{ display: "flex", gap: "0.3rem", flexWrap: "wrap" }}>
                        <Badge text={plugin.version} tone="info" />
                        <Badge text={normalizedStatus} tone={pluginSafetyTone(plugin)} />
                        <Badge text={plugin.enabled ? "enabled" : "disabled"} tone={plugin.enabled ? "ok" : "warn"} />
                      </div>
                    </div>

                    <div style={{ display: "flex", gap: "0.3rem", flexWrap: "wrap" }}>
                      <Badge text={`signature ${plugin.signature_status}`} tone={plugin.signature_status === "verified" ? "ok" : "danger"} />
                      <Badge text={`dependency ${plugin.dependency_status}`} tone={plugin.dependency_status === "compatible" ? "ok" : "warn"} />
                      <Badge text={`sandbox ${plugin.sandbox_status}`} tone={plugin.sandbox_status === "isolated" ? "ok" : "warn"} />
                    </div>

                    {plugin.failure_reason ? (
                      <div style={{ color: "var(--danger)", fontSize: "0.85rem" }}>
                        Failure reason: {plugin.failure_reason}
                      </div>
                    ) : null}
                    {plugin.warning ? (
                      <div style={{ color: "var(--warn)", fontSize: "0.85rem" }}>
                        Warning: {plugin.warning}
                      </div>
                    ) : null}
                    {!safetyReady && normalizedStatus !== "failed" ? (
                      <div style={{ color: "var(--ink-3)", fontSize: "0.85rem" }}>
                        Safety gate blocks enable until signature, dependency, and sandbox checks are compatible.
                      </div>
                    ) : null}

                    <div className="mono" style={{ color: "var(--ink-3)", fontSize: "0.72rem" }}>
                      {plugin.plugin_key} | queue {plugin.queue_status}
                    </div>

                    <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap" }}>
                      <Button
                        tone="primary"
                        type="button"
                        disabled={!canEnable || actionLoading || enableMutation.isPending}
                        onClick={() => handleEnable(plugin.plugin_id)}
                      >
                        {actionLoading && !plugin.enabled ? "Working..." : "Enable"}
                      </Button>
                      <Button
                        tone="ghost"
                        type="button"
                        disabled={!canDisable || actionLoading || disableMutation.isPending}
                        onClick={() => handleDisable(plugin.plugin_id)}
                      >
                        {actionLoading && plugin.enabled ? "Working..." : "Disable"}
                      </Button>
                    </div>
                  </article>
                );
              })}
            </div>
          )}
        </QueryState>
      </Panel>
    </div>
  );
}

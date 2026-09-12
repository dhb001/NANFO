import { FormEvent, useState } from "react";

import { useDisablePlugin, useEnablePlugin, useInstallPlugin, usePluginsQuery, useUninstallPlugin } from "@/features/plugins/hooks";
import { canAccessRoute, hasPermission } from "@/features/auth/permissions";
import { toErrorMessage } from "@/shared/lib/errors";
import { useAuthStore } from "@/shared/state/auth-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { AsyncState } from "@/shared/ui/AsyncState";
import { Badge } from "@/shared/ui/Badge";
import { Button } from "@/shared/ui/Button";
import { Panel } from "@/shared/ui/Panel";
import { QueryState } from "@/shared/ui/QueryState";

export function PluginsPage() {
  const generation = useAuthStore((state) => state.generation);
  const scope = useWorkspaceStore((state) => `${state.organizationId}:${state.workspaceId}`);
  return <Registry key={`${generation}:${scope}`} />;
}

function Registry() {
  const token = useAuthStore((state) => state.accessToken);
  const allowed = useAuthStore((state) => canAccessRoute(state.profile, "/ops/plugins") && hasPermission(state.profile, "write:config"));
  const [fields, setFields] = useState({ plugin_key: "", name: "", version: "1.0.0", signer: "", signature: "", requires: "", permissions: "read:telemetry" });
  const [status, setStatus] = useState<"installed" | "enabled" | "disabled" | "failed" | undefined>();
  const [search, setSearch] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const plugins = usePluginsQuery(token, { status, search: search.trim() || undefined, limit: 200 });
  const install = useInstallPlugin(token);
  const enable = useEnablePlugin(token);
  const disable = useDisablePlugin(token);
  const uninstall = useUninstallPlugin(token);
  const pending = install.isPending || enable.isPending || disable.isPending || uninstall.isPending;

  async function action(kind: "install" | "enable" | "disable", id?: string) {
    if (!allowed || pending) return;
    setError(null); setNotice("");
    try {
      const split = (value: string) => value.split(",").map((part) => part.trim()).filter(Boolean);
      const result = kind === "install" ? await install.mutateAsync({
        plugin_key: fields.plugin_key.trim(), name: fields.name.trim(), version: fields.version.trim(),
        signer: fields.signer.trim(), signature: fields.signature.trim(),
        dependencies: { platform_version: "0.1.0", requires: split(fields.requires) },
        sandbox: { isolation_mode: "process", permissions: split(fields.permissions) }, metadata: {},
      }) : await (kind === "enable" ? enable : disable).mutateAsync(id as string);
      if (result.status === "failed") throw new Error(result.failure_reason || "Registry update failed.");
      setNotice(`Registry updated: ${result.status}. No package executed.`);
    } catch (cause) { setError(toErrorMessage(cause)); }
  }

  function submit(event: FormEvent) { event.preventDefault(); void action("install"); }

  async function remove(id: string) {
    if (!allowed || pending || confirmId !== id) return;
    setError(null); setNotice("");
    try {
      await uninstall.mutateAsync(id);
      setConfirmId(null);
      setNotice("Registry entry uninstalled. Audit history preserved; no package removed.");
    } catch (cause) { setError(toErrorMessage(cause)); }
  }

  const inputs = [
    ["plugin_key", "Plugin Key", 120], ["name", "Name", 120], ["version", "Version", 40],
    ["signer", "Signer", 120], ["signature", "Signature", 256],
    ["requires", "Dependencies (comma-separated)", undefined], ["permissions", "Sandbox permissions", undefined],
  ] as const;

  return <div style={{ display: "grid", gap: "1rem", minWidth: 0 }}>
    <Panel title="Plugin Metadata Registry" subtitle="Metadata only. No package execution, signature verification, compatibility testing or sandbox safety guarantee.">
      <form onSubmit={submit} style={{ display: "grid", gap: "0.65rem" }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 180px), 1fr))", gap: "0.55rem" }}>
          {inputs.map(([key, label, maxLength]) => <label key={key} style={{ display: "grid", gap: "0.3rem" }}>
            <span>{label}</span>
            <input aria-label={label} value={fields[key]} maxLength={maxLength}
              required={key !== "requires" && key !== "permissions"} minLength={key === "plugin_key" ? 3 : key === "signature" ? 8 : undefined}
              onChange={(event) => setFields({ ...fields, [key]: event.target.value })}
              style={{ minWidth: 0, border: "1px solid var(--line-soft)", borderRadius: 10, padding: "0.45rem" }} />
          </label>)}
        </div>
        <p>Enable and Disable change registry flags only. All declarations remain unverified.</p>
        <Button permission="write:config" type="submit" disabled={!allowed || pending}>Register Metadata</Button>
      </form>
    </Panel>
    {error ? <AsyncState title="Registry action failed" description={error} /> : null}
    {notice ? <p role="status">{notice}</p> : null}
    <Panel title="Plugin Registry"
      action={<div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap" }}>
        <input aria-label="Filter plugins" placeholder="Search plugins" value={search} onChange={(event) => setSearch(event.target.value)} />
        <select aria-label="Registry status" value={status ?? ""} onChange={(event) => setStatus(event.target.value as typeof status || undefined)}>
          <option value="">All</option>{["installed", "enabled", "disabled", "failed"].map((value) => <option key={value}>{value}</option>)}
        </select>
      </div>}>
      <QueryState query={plugins} hasData={(data) => data.items.length > 0} emptyTitle="No plugins in registry">
        {(data) => <div style={{ display: "grid", gap: "0.5rem", maxHeight: 540, overflow: "auto" }}>
          {data.items.map((plugin) => <article key={plugin.plugin_id} style={{ border: "1px solid var(--line-soft)", borderRadius: 10, padding: "0.6rem", display: "grid", gap: "0.4rem", overflowWrap: "anywhere" }}>
            <strong>{plugin.name} {plugin.version}</strong>
            <div style={{ display: "flex", gap: "0.3rem", flexWrap: "wrap" }}>
              <Badge text={`registry ${plugin.status}`} tone={plugin.status === "failed" ? "danger" : "info"} />
              <Badge text="signature declared_unverified" tone="warn" /><Badge text="dependencies declared_unverified" tone="warn" /><Badge text="permissions declared_unverified" tone="warn" /><Badge text="sandbox not_executed" tone="neutral" />
            </div>
            <span className="mono">{plugin.plugin_key} | queue {plugin.queue_status}</span>
            {plugin.failure_reason ? <span>Failure reason: {plugin.failure_reason}</span> : null}
            {plugin.warning ? <span>Warning: {plugin.warning}</span> : null}
            <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap" }}>
              <Button permission="write:config" disabled={!allowed || pending || plugin.enabled || !["installed", "disabled"].includes(plugin.status)} onClick={() => action("enable", plugin.plugin_id)}>Enable</Button>
              <Button permission="write:config" tone="ghost" disabled={!allowed || pending || !plugin.enabled} onClick={() => action("disable", plugin.plugin_id)}>Disable</Button>
              <Button permission="write:config" tone="danger" disabled={!allowed || pending || plugin.status === "uninstalled"} onClick={() => setConfirmId(plugin.plugin_id)}>Uninstall</Button>
            </div>
            {confirmId === plugin.plugin_id ? <div role="group" aria-label={`Confirm uninstall ${plugin.name}`}>
              <p>Uninstall metadata for {plugin.name}? Audit history remains; no package is stopped or removed.</p>
              <Button permission="write:config" tone="danger" disabled={!allowed || pending} onClick={() => remove(plugin.plugin_id)}>Confirm Uninstall</Button>{" "}
              <Button tone="ghost" disabled={pending} onClick={() => setConfirmId(null)}>Cancel</Button>
            </div> : null}
          </article>)}
        </div>}
      </QueryState>
    </Panel>
  </div>;
}

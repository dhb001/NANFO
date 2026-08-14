import { useEffect, useMemo, useState } from "react";
import { Panel } from "@/shared/ui/Panel";
import { StatTile } from "@/shared/ui/StatTile";
import { useAuthStore } from "@/shared/state/auth-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { useOrganizations, useOrgMembers, useWorkspaces } from "@/features/organizations/hooks";
import {
  useNetworks,
  useCreateNetwork,
  useDevices,
  useCreateDevice,
  useUpdateDeviceSpatialRef,
} from "@/features/networks/hooks";
import { QueryState } from "@/shared/ui/QueryState";
import { Button } from "@/shared/ui/Button";
import { useUiStore } from "@/shared/state/ui-store";
import { Badge } from "@/shared/ui/Badge";
import { useLiveStore } from "@/features/realtime/store";
import { AsyncState } from "@/shared/ui/AsyncState";
import { useIsNarrowViewport } from "@/shared/lib/viewport";

export function OverviewPage() {
  const token = useAuthStore((state) => state.accessToken);
  const orgId = useWorkspaceStore((state) => state.organizationId);
  const workspaceId = useWorkspaceStore((state) => state.workspaceId);
  const networkId = useWorkspaceStore((state) => state.networkId);
  const setOrganizationId = useWorkspaceStore((state) => state.setOrganizationId);
  const setWorkspaceId = useWorkspaceStore((state) => state.setWorkspaceId);
  const setNetworkId = useWorkspaceStore((state) => state.setNetworkId);
  const pushToast = useUiStore((state) => state.pushToast);
  const isNarrowViewport = useIsNarrowViewport();

  const orgsQuery = useOrganizations(token);
  const workspacesQuery = useWorkspaces(token, orgId);
  const membersQuery = useOrgMembers(token, orgId);
  const networksQuery = useNetworks(token, workspaceId);
  const devicesQuery = useDevices(token, networkId);

  const createNetworkMutation = useCreateNetwork(token, workspaceId);
  const createDeviceMutation = useCreateDevice(token, networkId);
  const updateSpatialRefMutation = useUpdateDeviceSpatialRef(token, networkId);

  const [spatialDrafts, setSpatialDrafts] = useState<Record<string, string>>({});

  const topologyStatus = useLiveStore((state) => state.topologyStatus);
  const telemetryStatus = useLiveStore((state) => state.telemetryStatus);
  const digitalTwinStatus = useLiveStore((state) => state.digitalTwinStatus);
  const alertsStatus = useLiveStore((state) => state.alertsStatus);

  useEffect(() => {
    if (!orgId && orgsQuery.data?.items?.[0]) {
      setOrganizationId(orgsQuery.data.items[0].org_id);
    }
  }, [orgId, orgsQuery.data, setOrganizationId]);

  useEffect(() => {
    if (!workspaceId && workspacesQuery.data?.items?.[0]) {
      setWorkspaceId(workspacesQuery.data.items[0].workspace_id);
    }
  }, [workspaceId, workspacesQuery.data, setWorkspaceId]);

  useEffect(() => {
    if (!networkId && networksQuery.data?.items?.[0]) {
      setNetworkId(networksQuery.data.items[0].network_id);
    }
  }, [networkId, networksQuery.data, setNetworkId]);

  useEffect(() => {
    if (workspaceId) {
      return;
    }
    if (networkId) {
      setNetworkId(null);
    }
  }, [workspaceId, networkId, setNetworkId]);

  const effectiveSpatialDrafts = useMemo(() => {
    const devices = devicesQuery.data?.items ?? [];
    const result: Record<string, string> = {};
    for (const device of devices) {
      result[device.device_id] = spatialDrafts[device.device_id] ?? (device.spatial_ref_id ?? "");
    }
    return result;
  }, [devicesQuery.data?.items, spatialDrafts]);

  async function updateSpatialRef(deviceId: string) {
    if (!networkId) {
      throw new Error("No network selected.");
    }
    const spatialRefId = effectiveSpatialDrafts[deviceId] ?? "";
    await updateSpatialRefMutation.mutateAsync({
      deviceId,
      spatialRefId: spatialRefId.trim() ? spatialRefId.trim() : null,
    });
    pushToast({
      title: "Spatial reference updated",
      description: `Device ${deviceId.slice(0, 8)} spatial_ref_id updated.`,
      tone: "ok",
    });
  }

  return (
    <>
      <section style={{ display: "grid", gridTemplateColumns: isNarrowViewport ? "repeat(2, minmax(0, 1fr))" : "repeat(4, minmax(0, 1fr))", gap: "0.65rem" }}>
        <StatTile label="Topology WS" value={topologyStatus.toUpperCase()} tone={topologyStatus === "open" ? "ok" : "warn"} />
        <StatTile label="Telemetry WS" value={telemetryStatus.toUpperCase()} tone={telemetryStatus === "open" ? "ok" : "warn"} />
        <StatTile label="Alerts WS" value={alertsStatus.toUpperCase()} tone={alertsStatus === "open" ? "ok" : "warn"} />
        <StatTile
          label="Digital Twin WS"
          value={digitalTwinStatus.toUpperCase()}
          tone={digitalTwinStatus === "open" ? "ok" : "warn"}
        />
      </section>

      {!workspaceId ? (
        <AsyncState
          title="Workspace context required"
          description="Open Tenancy, create or select a workspace, then return to proceed with network and device workflows."
        />
      ) : null}

      <div style={{ display: "grid", gridTemplateColumns: isNarrowViewport ? "1fr" : "1.2fr 1fr", gap: "1rem", alignItems: "start" }}>
        <Panel title="Organization and Workspace" subtitle="VS1 tenancy flows with keyboard-accessible selectors">
          <div style={{ display: "grid", gap: "0.8rem" }}>
            <QueryState
              query={orgsQuery}
              hasData={(data) => data.items.length > 0}
              emptyTitle="No organizations"
              emptyDescription="Create an organization in backend fixtures or live API first."
            >
              {(orgs) => (
                <label style={{ display: "grid", gap: "0.3rem" }}>
                  <span className="mono" style={{ fontSize: "0.8rem", color: "var(--ink-3)" }}>
                    Organization
                  </span>
                  <select
                    value={orgId ?? ""}
                    onChange={(event) => setOrganizationId(event.target.value)}
                    style={{
                      border: "1px solid var(--line-soft)",
                      borderRadius: "10px",
                      padding: "0.48rem 0.5rem",
                    }}
                  >
                    {orgs.items.map((org) => (
                      <option key={org.org_id} value={org.org_id}>
                        {org.name}
                      </option>
                    ))}
                  </select>
                </label>
              )}
            </QueryState>

            <QueryState
              query={workspacesQuery}
              hasData={(data) => data.items.length > 0}
              emptyTitle="No workspaces"
              emptyDescription="No workspace found for the current organization."
            >
              {(workspaces) => (
                <label style={{ display: "grid", gap: "0.3rem" }}>
                  <span className="mono" style={{ fontSize: "0.8rem", color: "var(--ink-3)" }}>
                    Workspace
                  </span>
                  <select
                    value={workspaceId ?? ""}
                    onChange={(event) => setWorkspaceId(event.target.value)}
                    style={{
                      border: "1px solid var(--line-soft)",
                      borderRadius: "10px",
                      padding: "0.48rem 0.5rem",
                    }}
                  >
                    {workspaces.items.map((workspace) => (
                      <option key={workspace.workspace_id} value={workspace.workspace_id}>
                        {workspace.name}
                      </option>
                    ))}
                  </select>
                </label>
              )}
            </QueryState>

            <QueryState query={membersQuery}>
              {(members) => (
                <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
                  {members.items.slice(0, 6).map((member) => (
                    <Badge key={member.user_id} text={`${member.org_role} ${member.user_id.slice(0, 8)}`} tone="info" />
                  ))}
                </div>
              )}
            </QueryState>
          </div>
        </Panel>

        <Panel
          title="Workspace Capacity"
          subtitle="Density snapshot for selected tenancy"
          action={
            <Button
              onClick={async () => {
                if (!workspaceId) {
                  pushToast({
                    title: "No workspace selected",
                    description: "Use the Tenancy page to select an active workspace first.",
                    tone: "warn",
                  });
                  return;
                }
                await createNetworkMutation.mutateAsync(`Network-${Date.now().toString().slice(-4)}`);
                pushToast({
                  title: "Network created",
                  description: "VS1 create network flow succeeded.",
                  tone: "ok",
                });
              }}
              disabled={!workspaceId || createNetworkMutation.isPending}
            >
              {createNetworkMutation.isPending ? "Creating..." : "Create Network"}
            </Button>
          }
        >
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.6rem" }}>
            <StatTile label="Networks" value={String(networksQuery.data?.items.length ?? 0)} />
            <StatTile label="Devices" value={String(devicesQuery.data?.items.length ?? 0)} />
          </div>
        </Panel>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: isNarrowViewport ? "1fr" : "1fr 1fr", gap: "1rem", alignItems: "start" }}>
        <Panel title="Networks" subtitle="Select active network context for all views">
          <QueryState
            query={networksQuery}
            hasData={(data) => data.items.length > 0}
            emptyTitle="No networks"
            emptyDescription="Use Create Network to initialize workspace infrastructure."
          >
            {(networks) => (
              <div style={{ display: "grid", gap: "0.45rem" }}>
                {networks.items.map((network) => (
                  <button
                    key={network.network_id}
                    onClick={() => setNetworkId(network.network_id)}
                    style={{
                      textAlign: "left",
                      border: "1px solid var(--line-soft)",
                      borderRadius: "10px",
                      padding: "0.58rem 0.62rem",
                      background:
                        networkId === network.network_id
                          ? "color-mix(in srgb, var(--brand) 14%, white)"
                          : "transparent",
                    }}
                  >
                    <div style={{ fontWeight: 600 }}>{network.name}</div>
                    <div className="mono" style={{ color: "var(--ink-3)", fontSize: "0.75rem" }}>
                      {network.network_id}
                    </div>
                  </button>
                ))}
              </div>
            )}
          </QueryState>
        </Panel>

        <Panel
          title="Devices"
          subtitle="Create devices and seed digital twin topology"
          action={
            <Button
              onClick={async () => {
                if (!networkId) {
                  pushToast({
                    title: "No network selected",
                    description: "Create or select a network before adding devices.",
                    tone: "warn",
                  });
                  return;
                }
                await createDeviceMutation.mutateAsync({
                  hostname: `sw-${Date.now().toString().slice(-4)}`,
                  deviceType: "switch",
                  spatialRefId: `campus-a/building-1/floor-1/rack-${Math.ceil(Math.random() * 8)}`,
                });
                pushToast({
                  title: "Device created",
                  description: "Topology and realtime channels will fan out device lifecycle events.",
                  tone: "ok",
                });
              }}
              disabled={!networkId || createDeviceMutation.isPending}
            >
              {createDeviceMutation.isPending ? "Adding..." : "Add Device"}
            </Button>
          }
        >
          <QueryState
            query={devicesQuery}
            hasData={(data) => data.items.length > 0}
            emptyTitle="No devices"
            emptyDescription="Create a first device to populate topology and telemetry joins."
          >
            {(devices) => (
              <div style={{ display: "grid", gap: "0.4rem" }}>
                {devices.items.map((device) => (
                  <div
                    key={device.device_id}
                    style={{
                      border: "1px solid var(--line-soft)",
                      borderRadius: "10px",
                      padding: "0.55rem 0.58rem",
                      display: "grid",
                      gap: "0.2rem",
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between" }}>
                      <strong>{device.hostname}</strong>
                      <Badge text={device.status} tone={device.status === "active" ? "ok" : "warn"} />
                    </div>
                    <div className="mono" style={{ color: "var(--ink-3)", fontSize: "0.74rem" }}>
                      {device.device_id}
                    </div>
                    <div className="mono" style={{ color: "var(--ink-3)", fontSize: "0.74rem" }}>
                      {device.spatial_ref_id ?? "spatial_ref_id: none"}
                    </div>
                    <div style={{ display: "flex", gap: "0.4rem" }}>
                      <input
                        value={effectiveSpatialDrafts[device.device_id] ?? ""}
                        onChange={(event) =>
                          setSpatialDrafts((previous) => ({
                            ...previous,
                            [device.device_id]: event.target.value,
                          }))
                        }
                        aria-label={`Spatial reference for ${device.hostname}`}
                        placeholder="campus-a/building-1/floor-2/rack-4"
                        style={{
                          border: "1px solid var(--line-soft)",
                          borderRadius: "8px",
                          padding: "0.28rem 0.38rem",
                          flex: 1,
                          fontFamily: "var(--font-mono)",
                          fontSize: "0.74rem",
                        }}
                      />
                      <Button
                        tone="ghost"
                        type="button"
                        style={{ padding: "0.26rem 0.46rem" }}
                        onClick={async () => {
                          try {
                            await updateSpatialRef(device.device_id);
                          } catch (error) {
                            pushToast({
                              title: "Spatial update failed",
                              description: error instanceof Error ? error.message : "Unexpected error",
                              tone: "danger",
                            });
                          }
                        }}
                        disabled={updateSpatialRefMutation.isPending || !networkId}
                      >
                        Save
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </QueryState>
        </Panel>
      </div>
    </>
  );
}

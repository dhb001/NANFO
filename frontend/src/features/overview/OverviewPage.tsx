import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
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
import { NetworkArtwork } from "@/shared/ui/NetworkArtwork";
import { canAccessRoute } from "@/features/auth/permissions";

export function OverviewPage() {
  const token = useAuthStore((state) => state.accessToken);
  const orgId = useWorkspaceStore((state) => state.organizationId);
  const workspaceId = useWorkspaceStore((state) => state.workspaceId);
  const networkId = useWorkspaceStore((state) => state.networkId);
  const setOrganizationId = useWorkspaceStore((state) => state.setOrganizationId);
  const setWorkspaceId = useWorkspaceStore((state) => state.setWorkspaceId);
  const setNetworkId = useWorkspaceStore((state) => state.setNetworkId);
  const pushToast = useUiStore((state) => state.pushToast);
  const profile = useAuthStore((state) => state.profile);

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
  const activeNetwork = networksQuery.data?.items.find((network) => network.network_id === networkId);

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
      <header className="page-heading">
        <div><div className="eyebrow">Your network, in perspective</div><h1>Operations overview</h1><p>The context, connections and infrastructure behind every decision.</p></div>
        <span className="page-index">WORKSPACE / 01</span>
      </header>

      <section className="network-hero" aria-label="Selected network">
        <div className="network-hero-copy">
          <div className="eyebrow">Active network</div>
          <h2>{activeNetwork?.name ?? "Set your perspective."}</h2>
          <p>{activeNetwork ? "Explore your infrastructure, inspect its signals and test what comes next." : "Select a workspace and network below to begin exploring your infrastructure."}</p>
          {canAccessRoute(profile, "/ops/digital-twin") && networkId ? <Link className="hero-link" to="/ops/digital-twin">Explore infrastructure <span aria-hidden="true">↗</span></Link> : <Link className="hero-link" to="/ops/tenancy">Open workspace settings <span aria-hidden="true">↗</span></Link>}
        </div>
        <div className="hero-art"><NetworkArtwork /><span className="art-caption">Routing study / illustrative</span></div>
      </section>

      <section className="connection-strip" aria-label="Realtime connections">
        {[["Topology WS", topologyStatus], ["Telemetry WS", telemetryStatus], ["Alerts WS", alertsStatus], ["Digital Twin WS", digitalTwinStatus]].map(([label, status]) => (
          <div key={label} className="connection-item" data-connected={status === "open"}><i className="connection-dot" aria-hidden="true" /><span>{label}</span><strong>{status}</strong></div>
        ))}
      </section>

      {!workspaceId ? (
        <AsyncState
          title="Workspace context required"
          description="Open Tenancy, create or select a workspace, then return to proceed with network and device workflows."
        />
      ) : null}

      <div className="overview-grid">
        <Panel title="Organization and Workspace" subtitle="Set the scope for your operations">
          <div style={{ display: "grid", gap: "0.8rem" }}>
            <QueryState
              query={orgsQuery}
              hasData={(data) => data.items.length > 0}
              emptyTitle="No organizations"
              emptyDescription="Open Tenancy to create your first organization."
            >
              {(orgs) => (
                <label className="context-field">
                  <span>
                    Organization
                  </span>
                  <select
                    value={orgId ?? ""}
                    onChange={(event) => setOrganizationId(event.target.value)}
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
                <label className="context-field">
                  <span>
                    Workspace
                  </span>
                  <select
                    value={workspaceId ?? ""}
                    onChange={(event) => setWorkspaceId(event.target.value)}
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
          subtitle="Inventory in your current workspace and network"
          action={
            <Button
              permission="write:config"
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
                  description: "Your new network is ready to select.",
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
            <StatTile label="Networks" value={networksQuery.isSuccess ? String(networksQuery.data.items.length) : "—"} caption="In this workspace" />
            <StatTile label="Devices" value={devicesQuery.isSuccess ? String(devicesQuery.data.items.length) : "—"} caption="In the selected network" />
          </div>
        </Panel>
      </div>

      <div className="inventory-grid">
        <Panel title="Networks" subtitle="Select active network context for all views">
          <QueryState
            query={networksQuery}
            hasData={(data) => data.items.length > 0}
            emptyTitle="No networks"
            emptyDescription="Use Create Network to initialize workspace infrastructure."
          >
            {(networks) => (
              <div style={{ display: "grid", gap: "0.45rem" }}>
                {networks.items.map((network, index) => (
                  <button
                    key={network.network_id}
                    onClick={() => setNetworkId(network.network_id)}
                    className="network-choice"
                    aria-pressed={networkId === network.network_id}
                  >
                    <span className="network-choice-index" aria-hidden="true">{String(index + 1).padStart(2, "0")}</span>
                    <span><strong>{network.name}</strong><small>{network.network_id}</small></span>
                    <span aria-hidden="true">{networkId === network.network_id ? "●" : "↗"}</span>
                  </button>
                ))}
              </div>
            )}
          </QueryState>
        </Panel>

        <Panel
          title="Devices"
          subtitle="Device inventory and spatial references"
          action={
            <Button
              permission="write:config"
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
            emptyDescription="Add your first device to start building the network inventory."
          >
            {(devices) => (
              <div style={{ display: "grid", gap: "0.4rem" }}>
                {devices.items.map((device) => (
                  <div
                    key={device.device_id}
                    className="device-entry"
                  >
                    <div style={{ display: "flex", justifyContent: "space-between" }}>
                      <strong>{device.hostname}</strong>
                      <Badge text={device.status} tone={device.status === "active" ? "ok" : "warn"} />
                    </div>
                    <div className="device-reference">
                      {device.device_id}
                    </div>
                    <div className="device-reference">
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
                        className="spatial-input"
                      />
                      <Button
                        permission="write:config"
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

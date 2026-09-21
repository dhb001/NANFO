import { Link } from "react-router-dom";
import { Panel } from "@/shared/ui/Panel";
import { useAuthStore } from "@/shared/state/auth-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { useOrgMembers } from "@/features/organizations/hooks";
import { useDevices, useNetworks } from "@/features/networks/hooks";
import { QueryState } from "@/shared/ui/QueryState";
import { Badge } from "@/shared/ui/Badge";
import { useLiveStore } from "@/features/realtime/store";
import { AsyncState } from "@/shared/ui/AsyncState";
import { NetworkArtwork } from "@/shared/ui/NetworkArtwork";
import { canAccessRoute } from "@/features/auth/permissions";
import { ScopePicker } from "@/features/organizations/ScopePicker";
import { useOrgAuthority } from "@/features/organizations/useOrgAuthority";
import { OrgAuthorityStatus } from "@/features/organizations/OrgAuthorityStatus";
import type { Network } from "@/shared/types/network";
import { Pagination } from "@/shared/ui/Pagination";
import { InventoryPanel } from "./InventoryPanel";
import { StatTile } from "@/shared/ui/StatTile";
import { useScopeState } from "@/features/organizations/useScopeState";

export function OverviewPage() {
  const generation = useAuthStore((s) => s.generation);
  const orgId = useWorkspaceStore((s) => s.organizationId);
  return <OverviewContent key={`${generation}:${orgId}`} />;
}

function OverviewContent() {
  const token = useAuthStore((s) => s.accessToken);
  const profile = useAuthStore((s) => s.profile);
  const orgId = useWorkspaceStore((s) => s.organizationId);
  const workspaceId = useWorkspaceStore((s) => s.workspaceId);
  const networkId = useWorkspaceStore((s) => s.networkId);
  const [memberPage, setMemberPage] = useScopeState("overview-member-page", orgId, 1);
  const members = useOrgMembers(token, orgId, memberPage);
  const authority = useOrgAuthority(token, orgId, members.data);
  const networks = useNetworks(token, workspaceId);
  const devices = useDevices(token, networkId);
  const [selectedNetwork] = useScopeState<Network | null>("inventory-network-selected", workspaceId, null);
  const active = networks.data?.items.find((n) => n.network_id === networkId)
    ?? (selectedNetwork?.network_id === networkId ? selectedNetwork : null);
  const topologyStatus = useLiveStore((s) => s.topologyStatus);
  const telemetryStatus = useLiveStore((s) => s.telemetryStatus);
  const digitalTwinStatus = useLiveStore((s) => s.digitalTwinStatus);
  const alertsStatus = useLiveStore((s) => s.alertsStatus);
  return <>
    <header className="page-heading">
      <div><div className="eyebrow">Observe / Network atlas</div><h1>Operations overview</h1><p>A clear starting point for every network decision.</p></div>
      <span className="page-index" aria-hidden="true">N / O</span>
    </header>
    <section className="network-hero" aria-label="Selected network">
      <div className="network-hero-copy">
        <div className="eyebrow"><span className="hero-cross" aria-hidden="true">✳</span> Selected network</div>
        <h2>{active?.name ?? (networkId ? "Your selected network." : "Set your perspective.")}</h2>
        <p>{networkId ? active?.name ? "Your infrastructure. A new perspective." : networkId : "Select a workspace and network below to begin exploring your infrastructure."}</p>
        {canAccessRoute(profile, "/ops/digital-twin") && networkId ? <Link className="hero-link" to="/ops/digital-twin">Explore infrastructure <span aria-hidden="true">↗</span></Link> : <Link className="hero-link" to="/ops/tenancy">Open workspace settings <span aria-hidden="true">↗</span></Link>}
      </div>
      <div className="hero-art"><NetworkArtwork /><span className="art-caption">Routing study / illustrative</span></div>
    </section>
    <nav className="workflow-links" aria-label="Network workflows">
      {[
        { path: "/ops/topology-analysis", number: "01", label: "Understand the network", detail: "Connections & dependencies", icon: "P" },
        { path: "/ops/telemetry", number: "02", label: "Read the signals", detail: "Measurements & history", icon: "T" },
        { path: "/ops/simulation", number: "03", label: "Explore a change", detail: "Scenarios & comparison", icon: "S" },
      ].filter((item) => canAccessRoute(profile, item.path)).map((item) => <Link key={item.path} to={item.path} className="workflow-link"><span className="workflow-number">{item.number}</span><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true"><use href={`/navigation.svg#${item.icon}`} /></svg><span><strong>{item.label}</strong><small>{item.detail}</small></span><span className="workflow-arrow" aria-hidden="true">↗</span></Link>)}
    </nav>
    <section className="connection-strip" aria-label="Realtime connections">
      {[["Topology WS", topologyStatus], ["Telemetry WS", telemetryStatus], ["Alerts WS", alertsStatus], ["Digital Twin WS", digitalTwinStatus]].map(([label, status]) => <div key={label} className="connection-item" data-connected={status === "open"}><i className="connection-dot" aria-hidden="true" /><span>{label}</span><strong>{status}</strong></div>)}
    </section>
    {!workspaceId ? <AsyncState title="Workspace context required" description="Open Tenancy, create or select a workspace, then return to proceed with network and device workflows." /> : null}
    <div className="overview-grid"><Panel title="Organization and Workspace" subtitle="Set the scope for your operations">
      <ScopePicker />
      <QueryState query={members}>{(data) => <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem" }}>{data.items.map((member) => <Badge key={member.user_id} text={`${member.org_role} ${member.user_id.slice(0, 8)}`} tone="info" />)}</div>}</QueryState>
      <Pagination label="Members" page={memberPage} pageSize={20} total={members.data?.total ?? 0} pending={members.isFetching} onPageChange={setMemberPage} />
      <OrgAuthorityStatus authority={authority} />
    </Panel>
    <Panel title="Workspace Capacity" subtitle="Inventory in your current workspace and network">
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.6rem" }}>
        <StatTile label="Networks" value={networks.isSuccess ? String(networks.data.total) : "—"} caption="In this workspace" />
        <StatTile label="Devices" value={devices.isSuccess ? String(devices.data.total) : "—"} caption="In the selected network" />
      </div>
    </Panel></div>
    <InventoryPanel key={workspaceId ?? "none"} canWrite={authority.canWrite} />
  </>;
}

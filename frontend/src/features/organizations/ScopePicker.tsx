import { useEffect } from "react";
import { useScopeState } from "./useScopeState";
import { useOrganizations, useWorkspaces } from "./hooks";
import { useAuthStore } from "@/shared/state/auth-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { QueryState } from "@/shared/ui/QueryState";
import { Pagination } from "@/shared/ui/Pagination";

export function ScopePicker() {
  const token = useAuthStore((s) => s.accessToken);
  const orgId = useWorkspaceStore((s) => s.organizationId);
  const select = useWorkspaceStore((s) => s.setOrganizationId);
  const [page, setPage] = useScopeState("overview-org-page", null, 1);
  const organizations = useOrganizations(token, page);
  useEffect(() => {
    if (!orgId && organizations.data?.items[0]) select(organizations.data.items[0].org_id);
  }, [orgId, organizations.data, select]);
  return <div style={{ display: "grid", gap: "0.7rem" }}>
    <QueryState query={organizations} hasData={(d) => d.items.length > 0} emptyTitle="No organizations" emptyDescription="Open Tenancy to create an organization.">{(data) => <label className="context-field">Organization
      <select value={orgId ?? ""} onChange={(e) => select(e.target.value)}>
        {orgId && !data.items.some((org) => org.org_id === orgId) ? <option value={orgId}>Selected: {orgId} (off-page)</option> : null}
        {data.items.map((org) => <option key={org.org_id} value={org.org_id}>{org.name}</option>)}
      </select>
    </label>}</QueryState>
    <Pagination label="Organizations" page={page} pageSize={20} total={organizations.data?.total ?? 0} pending={organizations.isFetching} onPageChange={setPage} />
    <WorkspacePicker key={orgId} />
  </div>;
}

function WorkspacePicker() {
  const token = useAuthStore((s) => s.accessToken);
  const orgId = useWorkspaceStore((s) => s.organizationId);
  const workspaceId = useWorkspaceStore((s) => s.workspaceId);
  const select = useWorkspaceStore((s) => s.setWorkspaceId);
  const [page, setPage] = useScopeState("overview-workspace-page", orgId, 1);
  const workspaces = useWorkspaces(token, orgId, page);
  useEffect(() => {
    if (!workspaceId && workspaces.data?.items[0]) select(workspaces.data.items[0].workspace_id);
  }, [workspaceId, workspaces.data, select]);
  return <>
    <QueryState query={workspaces} hasData={(d) => d.items.length > 0} emptyTitle="No workspaces" emptyDescription="Create a workspace in Tenancy.">{(data) => <label className="context-field">Workspace
      <select value={workspaceId ?? ""} onChange={(e) => select(e.target.value)}>
        {workspaceId && !data.items.some((workspace) => workspace.workspace_id === workspaceId) ? <option value={workspaceId}>Selected: {workspaceId} (off-page)</option> : null}
        {data.items.map((workspace) => <option key={workspace.workspace_id} value={workspace.workspace_id}>{workspace.name}</option>)}
      </select>
    </label>}</QueryState>
    <Pagination label="Workspaces" page={page} pageSize={20} total={workspaces.data?.total ?? 0} pending={workspaces.isFetching} onPageChange={setPage} />
  </>;
}

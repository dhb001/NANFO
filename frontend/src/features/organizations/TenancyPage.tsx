import { useEffect, useState } from "react";
import { useAddOrgMember, useCreateOrganization, useCreateWorkspace, useDeleteOrganization, useDeleteWorkspace, useOrgMembers, useOrganizations, useRemoveOrgMember, useUpdateOrganization, useUpdateWorkspace, useWorkspaces } from "./hooks";
import { normalizeOrgSlug } from "./tenancy-logic";
import { DeleteResource, ResourceForm } from "./ResourceForm";
import { useOrgAuthority } from "./useOrgAuthority";
import { OrgAuthorityStatus } from "./OrgAuthorityStatus";
import { useScopeState } from "./useScopeState";
import { useAuthStore } from "@/shared/state/auth-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { Panel } from "@/shared/ui/Panel";
import { QueryState } from "@/shared/ui/QueryState";
import { Button } from "@/shared/ui/Button";
import { Pagination } from "@/shared/ui/Pagination";
import type { Organization, Workspace } from "@/shared/types/organization";
import { rememberFocus } from "@/shared/lib/focusRestore";

export function TenancyPage() {
  const generation = useAuthStore((s) => s.generation);
  return <TenancyContent key={generation} />;
}

function TenancyContent() {
  const token = useAuthStore((s) => s.accessToken);
  const orgId = useWorkspaceStore((s) => s.organizationId);
  const select = useWorkspaceStore((s) => s.setOrganizationId);
  const [page, setPage] = useScopeState("tenancy-org-page", null, 1);
  const [autoSelect, setAutoSelect] = useScopeState("tenancy-org-initial", null, true);
  const [selected, setSelected] = useScopeState<Organization | null>("tenancy-org-selected", null, null);
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [slugEdited, setSlugEdited] = useState(false);
  const orgs = useOrganizations(token, page);
  const create = useCreateOrganization(token);
  useEffect(() => {
    if (autoSelect && !orgId && orgs.data?.items[0]) select(orgs.data.items[0].org_id);
  }, [autoSelect, orgId, orgs.data, select]);
  useEffect(() => {
    if (orgs.data && page > Math.max(1, Math.ceil(orgs.data.total / 20))) setPage(Math.max(1, Math.ceil(orgs.data.total / 20)));
  }, [orgs.data, page, setPage]);
  const active = orgs.data?.items.find((org) => org.org_id === orgId) ?? (selected?.org_id === orgId ? selected : null);
  useEffect(() => {
    const current = orgs.data?.items.find((org) => org.org_id === orgId);
    if (current) setSelected(current);
  }, [orgs.data, orgId, setSelected]);
  return <div style={{ display: "grid", gap: "1rem" }}>
    <Panel title="Organization Scope" subtitle="Choose the organization that owns your workspaces and network inventory">
      <ResourceForm label="Create organization" submitLabel="Create Organization" disabled={!token} onRefresh={() => orgs.refetch()} onSubmit={async () => {
        const created = await create.mutateAsync({ name: name.trim(), slug });
        setName(""); setSlug(""); setSlugEdited(false); setSelected(created); select(created.org_id);
      }}>
        <label className="context-field">Organization Name<input required pattern=".*\S.*" maxLength={255} value={name} onChange={(e) => { setName(e.target.value); if (!slugEdited) setSlug(normalizeOrgSlug(e.target.value, "")); }} /></label>
        <label className="context-field">Slug<input required minLength={3} maxLength={63} pattern="[a-z0-9][a-z0-9\-]{1,61}[a-z0-9]" value={slug} onChange={(e) => { setSlugEdited(true); setSlug(e.target.value); }} /></label>
        <small>3–63 lowercase letters, digits or hyphens; begin and end with a letter or digit.</small>
      </ResourceForm>
      <QueryState query={orgs} hasData={(d) => d.items.length > 0} emptyTitle="No organizations" emptyDescription="Create an organization to establish tenant scope.">{(data) => <label className="context-field">Active Organization
        <select data-focus-key="tenancy-organization" value={orgId ?? ""} onChange={(e) => { setSelected(data.items.find((org) => org.org_id === e.target.value) ?? null); rememberFocus("tenancy-organization"); select(e.target.value); }}>
          <option value="" disabled>Select an organization</option>
          {orgId && !data.items.some((org) => org.org_id === orgId) ? <option value={orgId}>{active?.name ?? orgId} (selected, off-page)</option> : null}
          {data.items.map((org) => <option key={org.org_id} value={org.org_id}>{org.name} ({org.slug})</option>)}
        </select>
      </label>}</QueryState>
      <Pagination label="Organizations" page={page} pageSize={20} total={orgs.data?.total ?? 0} pending={orgs.isFetching} onPageChange={setPage} />
    </Panel>
    {orgId ? <OrganizationDetails key={orgId} organization={active} onDeleted={() => { setAutoSelect(false); setSelected(null); select(null); }} onSaved={setSelected} /> : null}
  </div>;
}

function OrganizationDetails({ organization, onDeleted, onSaved }: {
  organization: Organization | null; onDeleted: () => void; onSaved: (org: Organization) => void;
}) {
  const token = useAuthStore((s) => s.accessToken);
  const userId = useAuthStore((s) => s.userId);
  const orgId = useWorkspaceStore((s) => s.organizationId);
  const [page, setPage] = useScopeState("tenancy-member-page", orgId, 1);
  const [name, setName] = useState<string | null>(null);
  const [memberId, setMemberId] = useState("");
  const [role, setRole] = useState("Operator");
  const members = useOrgMembers(token, orgId, page);
  const authority = useOrgAuthority(token, orgId);
  const update = useUpdateOrganization(token, orgId);
  const remove = useDeleteOrganization(token, orgId);
  const addMember = useAddOrgMember(token, orgId);
  const removeMember = useRemoveOrgMember(token, orgId);
  const organizations = useOrganizations(token);
  useEffect(() => {
    if (members.data && page > Math.max(1, Math.ceil(members.data.total / 20))) setPage(Math.max(1, Math.ceil(members.data.total / 20)));
  }, [members.data, page, setPage]);
  return <>
    <Panel title="Organization administration" subtitle={`Current organization: ${organization?.name ?? orgId}`}>
      <OrgAuthorityStatus authority={authority} administration />
      <ResourceForm label="Edit organization" submitLabel="Save organization" disabled={!authority.canAdmin} onRefresh={() => organizations.refetch()} onSubmit={async () => { onSaved(await update.mutateAsync({ name: (name ?? organization?.name ?? "").trim() })); setName(null); }}>
        <label className="context-field">Organization name to edit<input required pattern=".*\S.*" maxLength={255} value={name ?? organization?.name ?? ""} onChange={(e) => setName(e.target.value)} /></label>
      </ResourceForm>
      <DeleteResource name="organization" disabled={!authority.canAdmin} detail="Its workspaces and network inventory will no longer be accessible through this scope. The slug remains reserved." onRefresh={() => organizations.refetch()} onDelete={async () => { await remove.mutateAsync(); onDeleted(); }} />
    </Panel>
    <WorkspaceAdministration canAdmin={authority.canAdmin} />
    <Panel title="Organization Members" subtitle="Add and remove members with explicit organization roles">
      <ResourceForm label="Add member" submitLabel="Add Member" disabled={!authority.canAdmin} onRefresh={() => members.refetch()} onSubmit={async () => { await addMember.mutateAsync({ userId: memberId.trim(), orgRole: role }); setMemberId(""); }}>
        <label className="context-field">User ID (UUID)<input required pattern="[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}" value={memberId} onChange={(e) => setMemberId(e.target.value)} /></label>
        <label className="context-field">Role<select aria-label="Role" value={role} onChange={(e) => setRole(e.target.value)}>{["Admin", "Operator", "Read-Only"].map((r) => <option key={r}>{r}</option>)}</select></label>
      </ResourceForm>
      <QueryState query={members} hasData={(d) => d.items.length > 0} emptyTitle="No members" emptyDescription="No membership records on this page.">{(data) => <div style={{ display: "grid", gap: "0.5rem" }}>{data.items.map((member) => <div className="device-entry" key={member.user_id}>
        <strong>{member.org_role}</strong><div className="device-reference">{member.user_id}</div>
        {member.user_id === userId ? <small>current session user</small> : <DeleteResource name={`member ${member.user_id}`} disabled={!authority.canAdmin} onRefresh={() => members.refetch()} onDelete={async () => { await removeMember.mutateAsync(member.user_id); }} detail="This user will lose access to this organization." />}
      </div>)}</div>}</QueryState>
      <Pagination label="Members" page={page} pageSize={20} total={members.data?.total ?? 0} pending={members.isFetching} onPageChange={setPage} />
    </Panel>
  </>;
}

function WorkspaceAdministration({ canAdmin }: { canAdmin: boolean }) {
  const token = useAuthStore((s) => s.accessToken);
  const orgId = useWorkspaceStore((s) => s.organizationId);
  const workspaceId = useWorkspaceStore((s) => s.workspaceId);
  const select = useWorkspaceStore((s) => s.setWorkspaceId);
  const [page, setPage] = useScopeState("tenancy-workspace-page", orgId, 1);
  const [autoSelect, setAutoSelect] = useScopeState("tenancy-workspace-initial", orgId, true);
  const [editing, setEditing] = useState<Workspace | null>(null);
  const workspaces = useWorkspaces(token, orgId, page);
  const create = useCreateWorkspace(token, orgId);
  const update = useUpdateWorkspace(token, orgId);
  const remove = useDeleteWorkspace(token, orgId);
  useEffect(() => {
    if (autoSelect && !workspaceId && workspaces.data?.items[0]) select(workspaces.data.items[0].workspace_id);
  }, [autoSelect, workspaceId, workspaces.data, select]);
  useEffect(() => {
    if (workspaces.data && page > Math.max(1, Math.ceil(workspaces.data.total / 20))) setPage(Math.max(1, Math.ceil(workspaces.data.total / 20)));
  }, [workspaces.data, page, setPage]);
  return <Panel title="Workspaces" subtitle="Create and select an active workspace within the organization">
    <p role="status">Selected workspace: {workspaceId ?? "None"}</p>
    <WorkspaceForm disabled={!canAdmin} onRefresh={() => workspaces.refetch()} onSave={async (input) => { const created = await create.mutateAsync(input); select(created.workspace_id); }} />
    <QueryState query={workspaces} hasData={(d) => d.items.length > 0} emptyTitle="No workspaces" emptyDescription="Create a workspace to unlock inventory.">{(data) => <div style={{ display: "grid", gap: "0.5rem" }}>{data.items.map((workspace) => <div key={workspace.workspace_id}>
      <button className="network-choice" data-focus-key={`tenancy-workspace:${workspace.workspace_id}`} aria-pressed={workspace.workspace_id === workspaceId} onClick={() => { rememberFocus(`tenancy-workspace:${workspace.workspace_id}`); select(workspace.workspace_id); }}><strong>{workspace.name}</strong><small>{workspace.workspace_id}</small></button>
      <Button permission="write:config" tone="ghost" disabled={!canAdmin} onClick={() => setEditing(workspace)}>Edit {workspace.name}</Button>
      <DeleteResource name={workspace.name} disabled={!canAdmin} onRefresh={() => workspaces.refetch()} detail="Network inventory in this workspace will no longer be accessible through this scope." onDelete={async () => {
        await remove.mutateAsync(workspace.workspace_id); setAutoSelect(false);
        if (useWorkspaceStore.getState().workspaceId === workspace.workspace_id) select(null);
        if (editing?.workspace_id === workspace.workspace_id) setEditing(null);
      }} />
    </div>)}</div>}</QueryState>
    <Pagination label="Workspaces" page={page} pageSize={20} total={workspaces.data?.total ?? 0} pending={workspaces.isFetching} onPageChange={setPage} />
    {editing ? <div><WorkspaceForm key={editing.workspace_id} workspace={editing} disabled={!canAdmin} onRefresh={() => workspaces.refetch()} onSave={async (input) => { await update.mutateAsync({ workspaceId: editing.workspace_id, changes: input }); setEditing(null); }} /><Button tone="ghost" onClick={() => setEditing(null)}>Close workspace editor</Button></div> : null}
  </Panel>;
}

function WorkspaceForm({ workspace, disabled, onSave, onRefresh }: { workspace?: Workspace; disabled: boolean; onSave: (input: { name: string; description: string }) => Promise<void>; onRefresh: () => Promise<unknown> }) {
  const [name, setName] = useState(workspace?.name ?? "");
  const [description, setDescription] = useState(workspace?.description ?? "");
  return <ResourceForm label={workspace ? "Edit workspace" : "Create workspace"} submitLabel={workspace ? "Save workspace" : "Create Workspace"} disabled={disabled} onRefresh={onRefresh} onSubmit={async () => { await onSave({ name: name.trim(), description: description.trim() }); if (!workspace) { setName(""); setDescription(""); } }}>
    <label className="context-field">Workspace Name<input required pattern=".*\S.*" maxLength={255} value={name} onChange={(e) => setName(e.target.value)} /></label>
    <label className="context-field">Description<textarea maxLength={4000} value={description} onChange={(e) => setDescription(e.target.value)} /></label>
  </ResourceForm>;
}

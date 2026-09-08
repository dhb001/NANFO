import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  useAddOrgMember,
  useCreateOrganization,
  useCreateWorkspace,
  useOrgMembers,
  useOrganizations,
  useRemoveOrgMember,
  useWorkspaces,
} from "@/features/organizations/hooks";
import { useAuthStore } from "@/shared/state/auth-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { useUiStore } from "@/shared/state/ui-store";
import { Panel } from "@/shared/ui/Panel";
import { QueryState } from "@/shared/ui/QueryState";
import { Button } from "@/shared/ui/Button";
import { Badge } from "@/shared/ui/Badge";
import { toErrorMessage } from "@/shared/lib/errors";
import { AsyncState } from "@/shared/ui/AsyncState";
import { normalizeOrgSlug, shouldClearWorkspace } from "@/features/organizations/tenancy-logic";
import { useIsNarrowViewport } from "@/shared/lib/viewport";

const roleOptions = ["Admin", "Operator", "Read-Only"];

export function TenancyPage() {
  const token = useAuthStore((state) => state.accessToken);
  const userId = useAuthStore((state) => state.userId);
  const orgId = useWorkspaceStore((state) => state.organizationId);
  const workspaceId = useWorkspaceStore((state) => state.workspaceId);
  const setOrganizationId = useWorkspaceStore((state) => state.setOrganizationId);
  const setWorkspaceId = useWorkspaceStore((state) => state.setWorkspaceId);
  const pushToast = useUiStore((state) => state.pushToast);
  const isNarrowViewport = useIsNarrowViewport();

  const orgsQuery = useOrganizations(token);
  const workspacesQuery = useWorkspaces(token, orgId);
  const membersQuery = useOrgMembers(token, orgId);

  const createOrgMutation = useCreateOrganization(token);
  const createWorkspaceMutation = useCreateWorkspace(token, orgId);
  const addMemberMutation = useAddOrgMember(token, orgId);
  const removeMemberMutation = useRemoveOrgMember(token, orgId);

  const [orgName, setOrgName] = useState("");
  const [orgSlug, setOrgSlug] = useState("");
  const [workspaceName, setWorkspaceName] = useState("");
  const [workspaceDescription, setWorkspaceDescription] = useState("");
  const [memberUserId, setMemberUserId] = useState("");
  const [memberRole, setMemberRole] = useState("Operator");

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
    if (orgId) {
      return;
    }
    if (shouldClearWorkspace(orgId, workspaceId)) {
      setWorkspaceId(null);
    }
  }, [orgId, workspaceId, setWorkspaceId]);

  const selectedOrg = useMemo(
    () => orgsQuery.data?.items.find((org) => org.org_id === orgId) ?? null,
    [orgId, orgsQuery.data],
  );

  async function onCreateOrganization(event: FormEvent) {
    event.preventDefault();
    const slug = normalizeOrgSlug(orgName, orgSlug);
    if (!orgName.trim() || !slug) {
      return;
    }
    try {
      const created = await createOrgMutation.mutateAsync({ name: orgName.trim(), slug });
      setOrgName("");
      setOrgSlug("");
      setOrganizationId(created.org_id);
      pushToast({
        title: "Organization created",
        description: `${created.name} is now active.`,
        tone: "ok",
      });
    } catch (error) {
      pushToast({
        title: "Create organization failed",
        description: toErrorMessage(error),
        tone: "danger",
      });
    }
  }

  async function onCreateWorkspace(event: FormEvent) {
    event.preventDefault();
    if (!orgId || !workspaceName.trim()) {
      return;
    }
    try {
      const created = await createWorkspaceMutation.mutateAsync({
        name: workspaceName.trim(),
        description: workspaceDescription.trim() || undefined,
      });
      setWorkspaceName("");
      setWorkspaceDescription("");
      setWorkspaceId(created.workspace_id);
      pushToast({
        title: "Workspace created",
        description: `${created.name} is now selected for operations flows.`,
        tone: "ok",
      });
    } catch (error) {
      pushToast({
        title: "Create workspace failed",
        description: toErrorMessage(error),
        tone: "danger",
      });
    }
  }

  async function onAddMember(event: FormEvent) {
    event.preventDefault();
    if (!orgId || !memberUserId.trim()) {
      return;
    }
    try {
      const member = await addMemberMutation.mutateAsync({
        userId: memberUserId.trim(),
        orgRole: memberRole,
      });
      setMemberUserId("");
      pushToast({
        title: "Member added",
        description: `${member.user_id} added as ${member.org_role}.`,
        tone: "ok",
      });
    } catch (error) {
      pushToast({
        title: "Add member failed",
        description: toErrorMessage(error),
        tone: "danger",
      });
    }
  }

  async function onRemoveMember(targetUserId: string) {
    try {
      await removeMemberMutation.mutateAsync(targetUserId);
      pushToast({
        title: "Member removed",
        description: `${targetUserId} was removed from organization membership.`,
        tone: "warn",
      });
    } catch (error) {
      pushToast({
        title: "Remove member failed",
        description: toErrorMessage(error),
        tone: "danger",
      });
    }
  }

  return (
    <div style={{ display: "grid", gap: "1rem" }}>
      <Panel title="Organization Scope" subtitle="VS1 tenancy foundations for organizations and workspaces">
        <div style={{ display: "grid", gridTemplateColumns: isNarrowViewport ? "1fr" : "1fr 1fr", gap: "0.8rem", alignItems: "start" }}>
          <form onSubmit={onCreateOrganization} style={{ display: "grid", gap: "0.55rem" }}>
            <label style={{ display: "grid", gap: "0.3rem" }}>
              <span className="mono" style={{ fontSize: "0.8rem", color: "var(--ink-3)" }}>
                Organization Name
              </span>
              <input
                value={orgName}
                onChange={(event) => {
                  const value = event.target.value;
                  setOrgName(value);
                  if (!orgSlug.trim()) {
                    setOrgSlug(normalizeOrgSlug(value, ""));
                  }
                }}
                required
                placeholder="North America NOC"
                style={{ border: "1px solid var(--line-soft)", borderRadius: "10px", padding: "0.48rem 0.5rem" }}
              />
            </label>

            <label style={{ display: "grid", gap: "0.3rem" }}>
              <span className="mono" style={{ fontSize: "0.8rem", color: "var(--ink-3)" }}>
                Slug
              </span>
              <input
                value={orgSlug}
                onChange={(event) => setOrgSlug(normalizeOrgSlug("", event.target.value))}
                required
                placeholder="north-america-noc"
                style={{ border: "1px solid var(--line-soft)", borderRadius: "10px", padding: "0.48rem 0.5rem" }}
              />
            </label>

            <div style={{ display: "flex", justifyContent: "flex-end" }}>
              <Button permission="write:config" type="submit" disabled={createOrgMutation.isPending || !token}>
                {createOrgMutation.isPending ? "Creating..." : "Create Organization"}
              </Button>
            </div>
          </form>

          <QueryState
            query={orgsQuery}
            hasData={(data) => data.items.length > 0}
            emptyTitle="No organizations"
            emptyDescription="Create your first organization to establish tenant scope."
          >
            {(orgs) => (
              <label style={{ display: "grid", gap: "0.3rem" }}>
                <span className="mono" style={{ fontSize: "0.8rem", color: "var(--ink-3)" }}>
                  Active Organization
                </span>
                <select
                  value={orgId ?? ""}
                  onChange={(event) => setOrganizationId(event.target.value)}
                  style={{ border: "1px solid var(--line-soft)", borderRadius: "10px", padding: "0.48rem 0.5rem" }}
                >
                  {orgs.items.map((org) => (
                    <option key={org.org_id} value={org.org_id}>
                      {org.name} ({org.slug})
                    </option>
                  ))}
                </select>
                {selectedOrg ? (
                  <div className="mono" style={{ color: "var(--ink-3)", fontSize: "0.75rem" }}>
                    {selectedOrg.org_id}
                  </div>
                ) : null}
              </label>
            )}
          </QueryState>
        </div>
        {createOrgMutation.isError ? (
          <div style={{ marginTop: "0.7rem" }}>
            <AsyncState title="Organization create failed" description={toErrorMessage(createOrgMutation.error)} />
          </div>
        ) : null}
      </Panel>

      <div style={{ display: "grid", gridTemplateColumns: isNarrowViewport ? "1fr" : "1fr 1fr", gap: "1rem", alignItems: "start" }}>
        <Panel title="Workspaces" subtitle="Create and select an active workspace within organization">
          <form onSubmit={onCreateWorkspace} style={{ display: "grid", gap: "0.55rem", marginBottom: "0.75rem" }}>
            <label style={{ display: "grid", gap: "0.3rem" }}>
              <span className="mono" style={{ fontSize: "0.8rem", color: "var(--ink-3)" }}>
                Workspace Name
              </span>
              <input
                value={workspaceName}
                onChange={(event) => setWorkspaceName(event.target.value)}
                required
                placeholder="Production"
                style={{ border: "1px solid var(--line-soft)", borderRadius: "10px", padding: "0.48rem 0.5rem" }}
              />
            </label>

            <label style={{ display: "grid", gap: "0.3rem" }}>
              <span className="mono" style={{ fontSize: "0.8rem", color: "var(--ink-3)" }}>
                Description
              </span>
              <input
                value={workspaceDescription}
                onChange={(event) => setWorkspaceDescription(event.target.value)}
                placeholder="Primary operations workspace"
                style={{ border: "1px solid var(--line-soft)", borderRadius: "10px", padding: "0.48rem 0.5rem" }}
              />
            </label>

            <div style={{ display: "flex", justifyContent: "flex-end" }}>
              <Button permission="write:config" type="submit" disabled={!orgId || createWorkspaceMutation.isPending}>
                {createWorkspaceMutation.isPending ? "Creating..." : "Create Workspace"}
              </Button>
            </div>
          </form>

          <QueryState
            query={workspacesQuery}
            hasData={(data) => data.items.length > 0}
            emptyTitle="No workspaces"
            emptyDescription="Create a workspace to unlock networks, telemetry, and simulations."
          >
            {(workspaces) => (
              <div style={{ display: "grid", gap: "0.42rem" }}>
                {workspaces.items.map((workspace) => (
                  <button
                    key={workspace.workspace_id}
                    onClick={() => setWorkspaceId(workspace.workspace_id)}
                    style={{
                      textAlign: "left",
                      border: "1px solid var(--line-soft)",
                      borderRadius: "10px",
                      padding: "0.5rem 0.55rem",
                      background:
                        workspaceId === workspace.workspace_id
                          ? "color-mix(in srgb, var(--brand) 14%, white)"
                          : "transparent",
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "0.5rem" }}>
                      <strong>{workspace.name}</strong>
                      {workspaceId === workspace.workspace_id ? <Badge text="active" tone="ok" /> : null}
                    </div>
                    <div className="mono" style={{ color: "var(--ink-3)", fontSize: "0.74rem" }}>
                      {workspace.workspace_id}
                    </div>
                  </button>
                ))}
              </div>
            )}
          </QueryState>
          {createWorkspaceMutation.isError ? (
            <div style={{ marginTop: "0.7rem" }}>
              <AsyncState title="Workspace create failed" description={toErrorMessage(createWorkspaceMutation.error)} />
            </div>
          ) : null}
        </Panel>

        <Panel title="Organization Members" subtitle="Add and remove org members with explicit organizational role">
          <form onSubmit={onAddMember} style={{ display: "grid", gap: "0.55rem", marginBottom: "0.75rem" }}>
            <label style={{ display: "grid", gap: "0.3rem" }}>
              <span className="mono" style={{ fontSize: "0.8rem", color: "var(--ink-3)" }}>
                User ID (UUID)
              </span>
              <input
                value={memberUserId}
                onChange={(event) => setMemberUserId(event.target.value)}
                required
                placeholder="00000000-0000-0000-0000-000000000000"
                style={{ border: "1px solid var(--line-soft)", borderRadius: "10px", padding: "0.48rem 0.5rem", fontFamily: "var(--font-mono)" }}
              />
            </label>

            <label style={{ display: "grid", gap: "0.3rem" }}>
              <span className="mono" style={{ fontSize: "0.8rem", color: "var(--ink-3)" }}>
                Role
              </span>
              <select
                value={memberRole}
                onChange={(event) => setMemberRole(event.target.value)}
                style={{ border: "1px solid var(--line-soft)", borderRadius: "10px", padding: "0.48rem 0.5rem" }}
              >
                {roleOptions.map((role) => (
                  <option key={role} value={role}>
                    {role}
                  </option>
                ))}
              </select>
            </label>

            <div style={{ display: "flex", justifyContent: "flex-end" }}>
              <Button permission="write:config" type="submit" disabled={!orgId || addMemberMutation.isPending}>
                {addMemberMutation.isPending ? "Adding..." : "Add Member"}
              </Button>
            </div>
          </form>

          <QueryState
            query={membersQuery}
            hasData={(data) => data.items.length > 0}
            emptyTitle="No members"
            emptyDescription="No membership records exist yet for this organization."
          >
            {(members) => (
              <div style={{ display: "grid", gap: "0.42rem", maxHeight: 360, overflow: "auto" }}>
                {members.items.map((member) => {
                  const isCurrentUser = userId ? member.user_id === userId : false;
                  return (
                    <div
                      key={member.user_id}
                      style={{
                        border: "1px solid var(--line-soft)",
                        borderRadius: "10px",
                        padding: "0.48rem 0.52rem",
                        display: "grid",
                        gap: "0.25rem",
                      }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                        <Badge text={member.org_role} tone="info" />
                        <Button
                          permission="write:config"
                          tone="ghost"
                          type="button"
                          disabled={removeMemberMutation.isPending || isCurrentUser}
                          onClick={() => onRemoveMember(member.user_id)}
                          style={{ padding: "0.28rem 0.5rem", fontWeight: 500 }}
                        >
                          Remove
                        </Button>
                      </div>
                      <div className="mono" style={{ color: "var(--ink-3)", fontSize: "0.74rem" }}>
                        {member.user_id}
                      </div>
                      {isCurrentUser ? (
                        <div className="mono" style={{ color: "var(--ink-3)", fontSize: "0.72rem" }}>
                          current session user
                        </div>
                      ) : null}
                    </div>
                  );
                })}
              </div>
            )}
          </QueryState>
          {addMemberMutation.isError ? (
            <div style={{ marginTop: "0.7rem" }}>
              <AsyncState title="Add member failed" description={toErrorMessage(addMemberMutation.error)} />
            </div>
          ) : null}
          {removeMemberMutation.isError ? (
            <div style={{ marginTop: "0.7rem" }}>
              <AsyncState title="Remove member failed" description={toErrorMessage(removeMemberMutation.error)} />
            </div>
          ) : null}
        </Panel>
      </div>
    </div>
  );
}

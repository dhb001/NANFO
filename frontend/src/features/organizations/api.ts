import { apiRequest, apiRequestNoContent } from "@/shared/lib/api";
import {
  OrgMember,
  OrgMemberList,
  Organization,
  OrganizationList,
  Workspace,
  WorkspaceList,
} from "@/shared/types/organization";

export function updateOrganization(token: string, orgId: string, body: { name: string }) {
  return apiRequest<Organization>(`/api/v1/organizations/${orgId}`, { method: "PATCH", token, body });
}

export function deleteOrganization(token: string, orgId: string) {
  return apiRequestNoContent(`/api/v1/organizations/${orgId}`, { token });
}

export function updateWorkspace(token: string, orgId: string, workspaceId: string, body: { name?: string; description?: string | null }) {
  return apiRequest<Workspace>(`/api/v1/organizations/${orgId}/workspaces/${workspaceId}`, { method: "PATCH", token, body });
}

export function deleteWorkspace(token: string, orgId: string, workspaceId: string) {
  return apiRequestNoContent(`/api/v1/organizations/${orgId}/workspaces/${workspaceId}`, { token });
}

export function createOrganization(token: string, body: { name: string; slug: string }) {
  return apiRequest<Organization>("/api/v1/organizations", {
    method: "POST",
    body,
    token,
  });
}

export function createWorkspace(token: string, orgId: string, body: { name: string; description?: string }) {
  return apiRequest<Workspace>(`/api/v1/organizations/${orgId}/workspaces`, {
    method: "POST",
    body,
    token,
  });
}

export function addOrgMember(token: string, orgId: string, body: { user_id: string; org_role: string }) {
  return apiRequest<OrgMember>(`/api/v1/organizations/${orgId}/members`, {
    method: "POST",
    body,
    token,
  });
}

export async function removeOrgMember(token: string, orgId: string, userId: string) {
  await apiRequestNoContent(`/api/v1/organizations/${orgId}/members/${userId}`, {
    method: "DELETE",
    token,
  });

  return { removed: true };
}

export function listOrganizations(token: string, page = 1, pageSize = 20, signal?: AbortSignal) {
  return apiRequest<OrganizationList>(`/api/v1/organizations?page=${page}&page_size=${pageSize}`, { token, signal });
}

/** One organization including `caller_role`; absent and non-member answer the same 404 (C6). */
export function getOrganization(token: string, orgId: string, signal?: AbortSignal) {
  return apiRequest<Organization>(`/api/v1/organizations/${encodeURIComponent(orgId)}`, { token, signal });
}

export function listWorkspaces(token: string, orgId: string, page = 1, pageSize = 20, signal?: AbortSignal) {
  return apiRequest<WorkspaceList>(
    `/api/v1/organizations/${orgId}/workspaces?page=${page}&page_size=${pageSize}`,
    { token, signal },
  );
}

export function listOrgMembers(token: string, orgId: string, page = 1, pageSize = 20, signal?: AbortSignal) {
  return apiRequest<OrgMemberList>(
    `/api/v1/organizations/${orgId}/members?page=${page}&page_size=${pageSize}`,
    { token, signal },
  );
}

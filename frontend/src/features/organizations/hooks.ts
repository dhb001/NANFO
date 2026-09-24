import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  addOrgMember,
  createOrganization,
  createWorkspace,
  listOrgMembers,
  listOrganizations,
  listWorkspaces,
  removeOrgMember,
  updateOrganization,
  deleteOrganization,
  updateWorkspace,
  deleteWorkspace,
} from "@/features/organizations/api";
import { useSessionScope } from "@/features/auth/sessionScope";
import { samePageSeries, scopedKey } from "@/shared/lib/queryKeys";
import { useAuthStore } from "@/shared/state/auth-store";

// Query identity is the session scope, never the access token (ADR-028).
const credential = (fallback: string | null) => useAuthStore.getState().accessToken ?? fallback;

export function useOrganizations(token: string | null, page = 1, pageSize = 20) {
  const scope = useSessionScope();
  const queryKey = scopedKey(scope, "orgs", page, pageSize);
  return useQuery({
    queryKey,
    queryFn: async ({ signal }) => (await scope.read((current) => listOrganizations(current, page, pageSize, signal), signal)).data,
    enabled: Boolean(token),
    placeholderData: (previous, previousQuery) => samePageSeries(previousQuery?.queryKey, queryKey, 3) ? keepPreviousData(previous) : undefined,
  });
}

export function useWorkspaces(token: string | null, orgId: string | null, page = 1, pageSize = 20) {
  const scope = useSessionScope();
  const queryKey = scopedKey(scope, "workspaces", orgId, page, pageSize);
  return useQuery({
    queryKey,
    queryFn: async ({ signal }) => (await scope.read((current) => listWorkspaces(current, orgId as string, page, pageSize, signal), signal)).data,
    enabled: Boolean(token && orgId),
    placeholderData: (previous, previousQuery) => samePageSeries(previousQuery?.queryKey, queryKey, 4) ? keepPreviousData(previous) : undefined,
  });
}

export function useOrgMembers(token: string | null, orgId: string | null, page = 1, pageSize = 20) {
  const scope = useSessionScope();
  const queryKey = scopedKey(scope, "org-members", orgId, page, pageSize);
  return useQuery({
    queryKey,
    queryFn: async ({ signal }) => (await scope.read((current) => listOrgMembers(current, orgId as string, page, pageSize, signal), signal)).data,
    enabled: Boolean(token && orgId),
    placeholderData: (previous, previousQuery) => samePageSeries(previousQuery?.queryKey, queryKey, 4) ? keepPreviousData(previous) : undefined,
  });
}

function useInvalidate() {
  const client = useQueryClient();
  const scope = useSessionScope();
  return (...domains: string[]) => {
    for (const domain of domains) void client.invalidateQueries({ queryKey: scopedKey(scope, domain) });
  };
}

export function useCreateOrganization(token: string | null) {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async (input: { name: string; slug: string }) => (await createOrganization(credential(token) as string, input)).data,
    onSuccess: () => invalidate("orgs"),
  });
}

export function useCreateWorkspace(token: string | null, orgId: string | null) {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async (input: { name: string; description?: string }) => (await createWorkspace(credential(token) as string, orgId as string, input)).data,
    onSuccess: () => invalidate("workspaces"),
  });
}

export function useAddOrgMember(token: string | null, orgId: string | null) {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async (input: { userId: string; orgRole: string }) => (await addOrgMember(credential(token) as string, orgId as string, {
      user_id: input.userId,
      org_role: input.orgRole,
    })).data,
    onSuccess: () => invalidate("org-members", "org-authority"),
  });
}

export function useRemoveOrgMember(token: string | null, orgId: string | null) {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async (userId: string) => removeOrgMember(credential(token) as string, orgId as string, userId),
    onSuccess: () => invalidate("org-members", "org-authority"),
  });
}

export function useUpdateOrganization(token: string | null, orgId: string | null) {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async (changes: { name: string }) => {
      const current = credential(token);
      if (!current || !orgId) throw new Error("Organization context is required.");
      return (await updateOrganization(current, orgId, changes)).data;
    },
    onSuccess: () => invalidate("orgs"),
  });
}

export function useDeleteOrganization(token: string | null, orgId: string | null) {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async () => {
      const current = credential(token);
      if (!current || !orgId) throw new Error("Organization context is required.");
      await deleteOrganization(current, orgId);
    },
    onSuccess: () => invalidate("orgs", "workspaces", "org-members", "org-authority", "networks", "devices"),
  });
}

export function useUpdateWorkspace(token: string | null, orgId: string | null) {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async ({ workspaceId, changes }: { workspaceId: string; changes: { name?: string; description?: string | null } }) => {
      const current = credential(token);
      if (!current || !orgId) throw new Error("Organization context is required.");
      return (await updateWorkspace(current, orgId, workspaceId, changes)).data;
    },
    onSuccess: () => invalidate("workspaces"),
  });
}

export function useDeleteWorkspace(token: string | null, orgId: string | null) {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async (workspaceId: string) => {
      const current = credential(token);
      if (!current || !orgId) throw new Error("Organization context is required.");
      await deleteWorkspace(current, orgId, workspaceId);
    },
    onSuccess: () => invalidate("workspaces", "networks", "devices"),
  });
}

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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

export function useOrganizations(token: string | null, page = 1, pageSize = 20) {
  return useQuery({
    queryKey: ["orgs", token, page, pageSize],
    queryFn: async () => {
      const response = await listOrganizations(token as string, page, pageSize);
      return { ...response.data, page, page_size: pageSize };
    },
    enabled: Boolean(token),
  });
}

export function useWorkspaces(token: string | null, orgId: string | null, page = 1, pageSize = 20) {
  return useQuery({
    queryKey: ["workspaces", token, orgId, page, pageSize],
    queryFn: async () => {
      const response = await listWorkspaces(token as string, orgId as string, page, pageSize);
      return { ...response.data, page, page_size: pageSize };
    },
    enabled: Boolean(token && orgId),
  });
}

export function useOrgMembers(token: string | null, orgId: string | null, page = 1, pageSize = 20) {
  return useQuery({
    queryKey: ["org-members", token, orgId, page, pageSize],
    queryFn: async () => {
      const response = await listOrgMembers(token as string, orgId as string, page, pageSize);
      return { ...response.data, page, page_size: pageSize };
    },
    enabled: Boolean(token && orgId),
  });
}

export function useCreateOrganization(token: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { name: string; slug: string }) => {
      const response = await createOrganization(token as string, input);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["orgs"] });
    },
  });
}

export function useCreateWorkspace(token: string | null, orgId: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { name: string; description?: string }) => {
      const response = await createWorkspace(token as string, orgId as string, input);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["workspaces"] });
    },
  });
}

export function useAddOrgMember(token: string | null, orgId: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { userId: string; orgRole: string }) => {
      const response = await addOrgMember(token as string, orgId as string, {
        user_id: input.userId,
        org_role: input.orgRole,
      });
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["org-members"] });
    },
  });
}

export function useRemoveOrgMember(token: string | null, orgId: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (userId: string) => removeOrgMember(token as string, orgId as string, userId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["org-members"] });
    },
  });
}

export function useUpdateOrganization(token: string | null, orgId: string | null) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (changes: { name: string }) => {
      if (!token || !orgId) throw new Error("Organization context is required.");
      return (await updateOrganization(token, orgId, changes)).data;
    },
    onSuccess: () => { void client.invalidateQueries({ queryKey: ["orgs"] }); },
  });
}

export function useDeleteOrganization(token: string | null, orgId: string | null) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      if (!token || !orgId) throw new Error("Organization context is required.");
      await deleteOrganization(token, orgId);
    },
    onSuccess: () => {
      for (const key of ["orgs", "workspaces", "org-members", "networks", "devices"]) void client.invalidateQueries({ queryKey: [key] });
    },
  });
}

export function useUpdateWorkspace(token: string | null, orgId: string | null) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ workspaceId, changes }: { workspaceId: string; changes: { name?: string; description?: string | null } }) => {
      if (!token || !orgId) throw new Error("Organization context is required.");
      return (await updateWorkspace(token, orgId, workspaceId, changes)).data;
    },
    onSuccess: () => { void client.invalidateQueries({ queryKey: ["workspaces"] }); },
  });
}

export function useDeleteWorkspace(token: string | null, orgId: string | null) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (workspaceId: string) => {
      if (!token || !orgId) throw new Error("Organization context is required.");
      await deleteWorkspace(token, orgId, workspaceId);
    },
    onSuccess: () => {
      for (const key of ["workspaces", "networks", "devices"]) void client.invalidateQueries({ queryKey: [key] });
    },
  });
}

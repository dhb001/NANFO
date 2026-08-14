import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  addOrgMember,
  createOrganization,
  createWorkspace,
  listOrgMembers,
  listOrganizations,
  listWorkspaces,
  removeOrgMember,
} from "@/features/organizations/api";

export function useOrganizations(token: string | null) {
  return useQuery({
    queryKey: ["orgs", token],
    queryFn: async () => {
      const response = await listOrganizations(token as string);
      return response.data;
    },
    enabled: Boolean(token),
  });
}

export function useWorkspaces(token: string | null, orgId: string | null) {
  return useQuery({
    queryKey: ["workspaces", token, orgId],
    queryFn: async () => {
      const response = await listWorkspaces(token as string, orgId as string);
      return response.data;
    },
    enabled: Boolean(token && orgId),
  });
}

export function useOrgMembers(token: string | null, orgId: string | null) {
  return useQuery({
    queryKey: ["org-members", token, orgId],
    queryFn: async () => {
      const response = await listOrgMembers(token as string, orgId as string);
      return response.data;
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
      queryClient.invalidateQueries({ queryKey: ["orgs", token] });
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
      queryClient.invalidateQueries({ queryKey: ["workspaces", token, orgId] });
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
      queryClient.invalidateQueries({ queryKey: ["org-members", token, orgId] });
    },
  });
}

export function useRemoveOrgMember(token: string | null, orgId: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (userId: string) => removeOrgMember(token as string, orgId as string, userId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["org-members", token, orgId] });
    },
  });
}

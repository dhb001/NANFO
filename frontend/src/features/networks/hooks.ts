import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createDevice,
  createNetwork,
  listDevices,
  listNetworks,
  updateDeviceSpatialRef,
} from "@/features/networks/api";

export function useNetworks(token: string | null, workspaceId: string | null) {
  return useQuery({
    queryKey: ["networks", token, workspaceId],
    queryFn: async () => {
      const response = await listNetworks(token as string, workspaceId as string);
      return response.data;
    },
    enabled: Boolean(token && workspaceId),
  });
}

export function useCreateNetwork(token: string | null, workspaceId: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (name: string) => {
      const response = await createNetwork(token as string, { workspace_id: workspaceId as string, name });
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["networks", token, workspaceId] });
    },
  });
}

export function useDevices(token: string | null, networkId: string | null) {
  return useQuery({
    queryKey: ["devices", token, networkId],
    queryFn: async () => {
      const response = await listDevices(token as string, networkId as string);
      return response.data;
    },
    enabled: Boolean(token && networkId),
  });
}

export function useCreateDevice(token: string | null, networkId: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { hostname: string; deviceType: string; spatialRefId?: string }) => {
      const response = await createDevice(token as string, networkId as string, {
        hostname: input.hostname,
        device_type: input.deviceType,
        spatial_ref_id: input.spatialRefId,
      });
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["devices", token, networkId] });
      queryClient.invalidateQueries({ queryKey: ["topology", token, networkId] });
    },
  });
}

export function useUpdateDeviceSpatialRef(token: string | null, networkId: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { deviceId: string; spatialRefId: string | null }) => {
      if (!token || !networkId) {
        throw new Error("Network context is required to update spatial references.");
      }
      const response = await updateDeviceSpatialRef(
        token,
        networkId,
        input.deviceId,
        input.spatialRefId,
      );
      return response.data;
    },
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ["devices", token, networkId] });
      queryClient.invalidateQueries({ queryKey: ["topology", token, networkId] });
      queryClient.invalidateQueries({ queryKey: ["topology-node", token, variables.deviceId] });
    },
  });
}

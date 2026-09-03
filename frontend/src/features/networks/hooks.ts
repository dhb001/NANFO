import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createDevice,
  createNetwork,
  listCampusBuildings,
  listCampusModelAssets,
  listDeviceGroups,
  listDevices,
  listNetworks,
  upsertCampusModelAssets,
  upsertCampusBuildings,
  upsertDeviceGroups,
  updateDeviceSpatialRef,
} from "@/features/networks/api";
import type {
  UpsertCampusModelAssetInput,
  UpsertDeviceGroupInput,
} from "@/shared/types/network";

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

export function useCampusBuildings(token: string | null, networkId: string | null) {
  return useQuery({
    queryKey: ["campus-buildings", token, networkId],
    queryFn: async () => {
      const response = await listCampusBuildings(token as string, networkId as string);
      return response.data;
    },
    enabled: Boolean(token && networkId),
  });
}

export function useUpsertCampusBuildings(token: string | null, networkId: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: {
      buildings: Array<{
        building_id: string;
        campus_key: string;
        building_key: string;
        label: string;
        geometry: "box" | "extrude";
        x: number;
        z: number;
        base_y: number;
        width: number;
        depth: number;
        height: number;
        floors: number;
        footprint: Array<[number, number]>;
        wall_material?: string | null;
        attenuation_db?: number | null;
        source?: string | null;
      }>;
      replaceExisting?: boolean;
    }) => {
      if (!token || !networkId) {
        throw new Error("Network context is required to update campus buildings.");
      }
      const response = await upsertCampusBuildings(token, networkId, input);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["campus-buildings", token, networkId] });
    },
  });
}

export function useCampusModelAssets(token: string | null, networkId: string | null) {
  return useQuery({
    queryKey: ["campus-model-assets", token, networkId],
    queryFn: async () => {
      const response = await listCampusModelAssets(token as string, networkId as string);
      return response.data;
    },
    enabled: Boolean(token && networkId),
  });
}

export function useUpsertCampusModelAssets(token: string | null, networkId: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: UpsertCampusModelAssetInput) => {
      if (!token || !networkId) {
        throw new Error("Network context is required to update campus model assets.");
      }
      const response = await upsertCampusModelAssets(token, networkId, input);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["campus-model-assets", token, networkId] });
    },
  });
}

export function useDeviceGroups(token: string | null, networkId: string | null) {
  return useQuery({
    queryKey: ["device-groups", token, networkId],
    queryFn: async () => {
      const response = await listDeviceGroups(token as string, networkId as string);
      return response.data;
    },
    enabled: Boolean(token && networkId),
  });
}

export function useUpsertDeviceGroups(token: string | null, networkId: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: {
      groups: UpsertDeviceGroupInput[];
      replaceExisting?: boolean;
    }) => {
      if (!token || !networkId) {
        throw new Error("Network context is required to update device groups.");
      }
      const response = await upsertDeviceGroups(token, networkId, input);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["device-groups", token, networkId] });
    },
  });
}

import { apiRequest, apiRequestNoContent } from "@/shared/lib/api";
import {
  CampusBuildingList,
  CampusModelAssetList,
  Device,
  DeviceGroupList,
  DeviceList,
  Network,
  NetworkList,
  UpsertCampusModelAssetInput,
  UpsertCampusBuildingInput,
  UpsertDeviceGroupInput,
  CreateNetworkInput,
  CreateDeviceInput,
  UpdateNetworkInput,
  UpdateDeviceInput,
} from "@/shared/types/network";

export function listNetworks(token: string, workspaceId: string, page = 1, pageSize = 20, signal?: AbortSignal) {
  const params = new URLSearchParams({ workspace_id: workspaceId, page: String(page), page_size: String(pageSize) });
  return apiRequest<NetworkList>(`/api/v1/networks?${params}`, { token, signal });
}

export function createNetwork(token: string, body: CreateNetworkInput) {
  return apiRequest<Network>("/api/v1/networks", {
    method: "POST",
    body,
    token,
  });
}

export function listDevices(token: string, networkId: string, page = 1, pageSize = 20, signal?: AbortSignal) {
  return apiRequest<DeviceList>(
    `/api/v1/networks/${encodeURIComponent(networkId)}/devices?page=${page}&page_size=${pageSize}`,
    { token, signal },
  );
}

export function createDevice(token: string, networkId: string, body: CreateDeviceInput) {
  return apiRequest<Device>(`/api/v1/networks/${networkId}/devices`, {
    method: "POST",
    body,
    token,
  });
}

export function updateNetwork(token: string, networkId: string, body: UpdateNetworkInput) {
  return apiRequest<Network>(`/api/v1/networks/${networkId}`, { method: "PATCH", body, token });
}

export function deleteNetwork(token: string, networkId: string) {
  return apiRequestNoContent(`/api/v1/networks/${networkId}`, { token });
}

export function updateDevice(token: string, networkId: string, deviceId: string, body: UpdateDeviceInput) {
  return apiRequest<Device>(`/api/v1/networks/${networkId}/devices/${deviceId}`, { method: "PATCH", body, token });
}

export function deleteDevice(token: string, networkId: string, deviceId: string) {
  return apiRequestNoContent(`/api/v1/networks/${networkId}/devices/${deviceId}`, { token });
}

export function updateDeviceSpatialRef(token: string, networkId: string, deviceId: string, spatialRefId: string | null) {
  return apiRequest<Device>(`/api/v1/networks/${networkId}/devices/${deviceId}`, {
    method: "PATCH",
    body: { spatial_ref_id: spatialRefId },
    token,
  });
}

export function listCampusBuildings(token: string, networkId: string, signal?: AbortSignal) {
  return apiRequest<CampusBuildingList>(`/api/v1/networks/${encodeURIComponent(networkId)}/campus/buildings`, {
    token, signal,
  });
}

export function upsertCampusBuildings(
  token: string,
  networkId: string,
  input: {
    buildings: UpsertCampusBuildingInput[];
    replaceExisting?: boolean;
  },
) {
  return apiRequest<CampusBuildingList>(`/api/v1/networks/${networkId}/campus/buildings`, {
    method: "POST",
    body: {
      buildings: input.buildings,
      replace_existing: input.replaceExisting ?? true,
    },
    token,
  });
}

export function listCampusModelAssets(token: string, networkId: string, page = 1, pageSize = 20, signal?: AbortSignal) {
  return apiRequest<CampusModelAssetList>(`/api/v1/networks/${encodeURIComponent(networkId)}/campus/model-assets?include_data=false&page=${page}&page_size=${pageSize}`, {
    token, signal,
  });
}

export function upsertCampusModelAssets(token: string, networkId: string, input: UpsertCampusModelAssetInput) {
  return apiRequest<CampusModelAssetList>(`/api/v1/networks/${networkId}/campus/model-assets`, {
    method: "POST",
    body: {
      model_file_name: input.model_file_name,
      model_mime_type: input.model_mime_type,
      model_data_base64: input.model_data_base64,
      model_sha256: input.model_sha256,
      model_size_bytes: input.model_size_bytes,
      mapping_by_device_id: input.mapping_by_device_id,
      ...(input.registration !== undefined ? { registration: input.registration } : {}),
      source: input.source ?? null,
      replace_existing: input.replace_existing ?? true,
    },
    token,
    // Model assets may be up to 12 MiB (C2 route limit): allow a slow uplink.
    timeoutMs: 120_000,
  });
}

export function listDeviceGroups(token: string, networkId: string, signal?: AbortSignal) {
  return apiRequest<DeviceGroupList>(`/api/v1/networks/${encodeURIComponent(networkId)}/device-groups`, {
    token, signal,
  });
}

export function upsertDeviceGroups(
  token: string,
  networkId: string,
  input: {
    groups: UpsertDeviceGroupInput[];
    replaceExisting?: boolean;
  },
) {
  return apiRequest<DeviceGroupList>(`/api/v1/networks/${networkId}/device-groups`, {
    method: "POST",
    body: {
      replace_existing: input.replaceExisting ?? false,
      groups: input.groups.map((group) => ({
        group_key: group.group_key,
        name: group.name,
        group_type: group.group_type,
        description: group.description ?? null,
        selector: group.selector ?? {},
        device_ids: group.device_ids ?? [],
        ...(group.expected_updated_at != null ? { expected_updated_at: group.expected_updated_at } : {}),
      })),
    },
    token,
  });
}

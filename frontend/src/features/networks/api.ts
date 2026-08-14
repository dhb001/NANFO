import { apiRequest } from "@/shared/lib/api";
import { Device, DeviceList, Network, NetworkList } from "@/shared/types/network";

interface CreateNetworkInput {
  workspace_id: string;
  name: string;
  description?: string;
  cidr?: string;
}

interface CreateDeviceInput {
  hostname: string;
  ip_address?: string;
  device_type: string;
  vendor?: string;
  model?: string;
  location_hint?: string;
  spatial_ref_id?: string;
}

export function listNetworks(token: string, workspaceId: string, page = 1, pageSize = 20) {
  return apiRequest<NetworkList>(
    `/api/v1/networks?workspace_id=${workspaceId}&page=${page}&page_size=${pageSize}`,
    { token },
  );
}

export function createNetwork(token: string, body: CreateNetworkInput) {
  return apiRequest<Network>("/api/v1/networks", {
    method: "POST",
    body,
    token,
  });
}

export function listDevices(token: string, networkId: string, page = 1, pageSize = 20) {
  return apiRequest<DeviceList>(
    `/api/v1/networks/${networkId}/devices?page=${page}&page_size=${pageSize}`,
    { token },
  );
}

export function createDevice(token: string, networkId: string, body: CreateDeviceInput) {
  return apiRequest<Device>(`/api/v1/networks/${networkId}/devices`, {
    method: "POST",
    body,
    token,
  });
}

export function updateDeviceSpatialRef(token: string, networkId: string, deviceId: string, spatialRefId: string | null) {
  return apiRequest<Device>(`/api/v1/networks/${networkId}/devices/${deviceId}`, {
    method: "PATCH",
    body: { spatial_ref_id: spatialRefId },
    token,
  });
}

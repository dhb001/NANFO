import type { CreateDeviceInput, Device, Network, UpdateDeviceInput, UpdateNetworkInput } from "@/shared/types/network";

export function changedNetworkFields(network: Network, input: UpdateNetworkInput): UpdateNetworkInput {
  return Object.fromEntries(Object.entries(input).filter(([key, value]) => network[key as keyof Network] !== value));
}

export function changedDeviceFields(device: Device, input: CreateDeviceInput): UpdateDeviceInput {
  return Object.fromEntries(Object.entries(input).filter(([key, value]) => device[key as keyof Device] !== value));
}

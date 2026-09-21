import { apiRequestNoContent } from "@/shared/lib/api";
import { listDeviceGroups, upsertCampusBuildings, upsertDeviceGroups } from "@/features/networks/api";
import type { UpsertDeviceGroupInput } from "@/shared/types/network";

export function retireModelAsset(token: string, networkId: string, assetId: string) {
  return apiRequestNoContent(`/api/v1/networks/${encodeURIComponent(networkId)}/campus/model-assets/${encodeURIComponent(assetId)}`, { method: "DELETE", token });
}

export function clearTwinRecords(token: string, networkId: string, kind: "groups" | "buildings") {
  return kind === "groups"
    ? upsertDeviceGroups(token, networkId, { replaceExisting: true, groups: [] })
    : upsertCampusBuildings(token, networkId, { replaceExisting: true, buildings: [] });
}

export function replaceReviewedGroups(token: string, networkId: string, groups: UpsertDeviceGroupInput[]) {
  return upsertDeviceGroups(token, networkId, { replaceExisting: true, groups });
}

/** Existing replacement API has no per-group delete or compare-and-swap revision. */
export async function retainedGroups(token: string, networkId: string, removedKey: string): Promise<UpsertDeviceGroupInput[]> {
  const { data } = await listDeviceGroups(token, networkId);
  if (data.items.length !== data.total || !data.items.some((group) => group.group_key === removedKey)) {
    throw new Error("Complete current group list required. Reload and select the group again.");
  }
  return data.items.filter((group) => group.group_key !== removedKey).map(({ group_key, name, group_type, description, selector, device_ids }) =>
    ({ group_key, name, group_type, description, selector, device_ids }));
}

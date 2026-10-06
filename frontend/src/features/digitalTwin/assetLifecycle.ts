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

/**
 * Fresh, complete list minus `removedKey`, each retained group pinned with C8
 * `expected_updated_at`: if any retained group changes before the replacement lands the
 * server answers 409 DEVICE_GROUP_CONFLICT and nothing is removed. When the editor's
 * `expectedRemovedUpdatedAt` is given, a group edited elsewhere since it was loaded is
 * not removed either.
 */
export async function retainedGroups(token: string, networkId: string, removedKey: string, expectedRemovedUpdatedAt?: string | null): Promise<UpsertDeviceGroupInput[]> {
  const { data } = await listDeviceGroups(token, networkId);
  const removed = data.items.find((group) => group.group_key === removedKey);
  if (data.items.length !== data.total || !removed) {
    throw new Error("Complete current group list required. Reload and select the group again.");
  }
  if (expectedRemovedUpdatedAt && removed.updated_at !== expectedRemovedUpdatedAt) {
    throw new Error(`Group ${removedKey} changed on the server since it was loaded. Reload groups and review it again.`);
  }
  return data.items.filter((group) => group.group_key !== removedKey).map(({ group_key, name, group_type, description, selector, device_ids, updated_at }) =>
    ({ group_key, name, group_type, description, selector, device_ids, expected_updated_at: updated_at }));
}

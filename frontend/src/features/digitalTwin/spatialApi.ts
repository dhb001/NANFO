import { apiRequest } from "@/shared/lib/api";
import type { PutSpatialScene } from "@/shared/types/spatial";
import { validateSpatialSnapshot } from "./spatialScene";

export async function getSpatialScene(token: string, networkId: string, signal?: AbortSignal) {
  const response = await apiRequest<unknown>(`/api/v1/networks/${encodeURIComponent(networkId)}/spatial-scene`, { token, ...(signal ? { signal } : {}) });
  return validateSpatialSnapshot(response.data);
}

export async function putSpatialScene(token: string, networkId: string, body: PutSpatialScene) {
  const response = await apiRequest<unknown>(`/api/v1/networks/${encodeURIComponent(networkId)}/spatial-scene`, { token, method: "PUT", body });
  return validateSpatialSnapshot(response.data);
}

export interface SpatialHistoryPage {
  items: Array<{ revision: number; recorded_at: string; actor_id: string | null; origin: "replacement" | "baseline"; object_count: number }>;
  total: number; page: number; page_size: number;
}
export async function getSpatialHistory(token: string, networkId: string, page: number, signal?: AbortSignal): Promise<SpatialHistoryPage> {
  const { data } = await apiRequest<SpatialHistoryPage>(`/api/v1/networks/${encodeURIComponent(networkId)}/spatial-scene/history?page=${page}&page_size=20`, { token, ...(signal ? { signal } : {}) });
  if (!Array.isArray(data.items) || data.items.length > 20 || data.page !== page || data.page_size !== 20 || !Number.isSafeInteger(data.total) || data.total < 0 || data.items.some((item) =>
    !Number.isSafeInteger(item.revision) || item.revision < 0 || !Number.isSafeInteger(item.object_count) || item.object_count < 0 || item.object_count > 10000 ||
    !["replacement", "baseline"].includes(item.origin) || typeof item.recorded_at !== "string" || !Number.isFinite(Date.parse(item.recorded_at)) || (item.actor_id !== null && typeof item.actor_id !== "string"))) throw new Error("Invalid spatial history response.");
  return data;
}
export async function getSpatialRevision(token: string, networkId: string, revision: number, signal?: AbortSignal) {
  const { data } = await apiRequest<unknown>(`/api/v1/networks/${encodeURIComponent(networkId)}/spatial-scene/history/${revision}`, { token, ...(signal ? { signal } : {}) });
  const scene = validateSpatialSnapshot(data);
  if (scene.revision !== revision) throw new Error("History revision mismatch.");
  return scene;
}

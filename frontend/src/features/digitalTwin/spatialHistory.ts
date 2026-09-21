import type { SpatialSceneSnapshot } from "@/shared/types/spatial";

/** Restore direction: current → selected historical document. Object order is immaterial. */
export function diffSpatialScenes(current: SpatialSceneSnapshot, target: SpatialSceneSnapshot) {
  const before = new Map(current.objects.map((item) => [item.object_id, item]));
  const after = new Map(target.objects.map((item) => [item.object_id, item]));
  return {
    added: target.objects.filter((item) => !before.has(item.object_id)).map((item) => item.object_id),
    removed: current.objects.filter((item) => !after.has(item.object_id)).map((item) => item.object_id),
    changed: target.objects.flatMap((item) => {
      const previous = before.get(item.object_id);
      if (!previous) return [];
      const fields = ([...new Set([...Object.keys(previous), ...Object.keys(item)])] as Array<keyof typeof item>).filter((key) => JSON.stringify(previous[key]) !== JSON.stringify(item[key]));
      return fields.length ? [{ id: item.object_id, fields }] : [];
    }),
  };
}

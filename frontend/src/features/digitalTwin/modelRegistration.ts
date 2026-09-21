import type { AssetRegistration } from "@/shared/types/network";

export function validateRegistration(value: unknown): AssetRegistration | null {
  if (value == null) return null;
  const item = value as AssetRegistration;
  const exact = (object: object, keys: string[]) => Object.keys(object).length === keys.length && keys.every((key) => Object.hasOwn(object, key));
  const valid = item.version === 1 && item.target_units === "m" && item.target_up_axis === "y" &&
    exact(item, ["version", "translation", "rotation", "scale", "target_units", "target_up_axis", "source"]) &&
    typeof item.source === "string" && item.source.trim() && item.source.length <= 128 && !item.source.includes("\0") &&
    [item.translation, item.rotation, item.scale].every((vector) => vector && exact(vector, ["x", "y", "z"]) && [vector.x, vector.y, vector.z].every((n) => typeof n === "number" && Number.isFinite(n))) &&
    Object.values(item.translation).every((n) => Math.abs(n) <= 1000000) && Object.values(item.rotation).every((n) => Math.abs(n) <= 2 * Math.PI) &&
    Object.values(item.scale).every((n) => n >= 0.000001 && n <= 1000000);
  if (!valid) throw new Error("Invalid asset registration.");
  return { version: 1, translation: { ...item.translation }, rotation: { ...item.rotation }, scale: { ...item.scale }, target_units: "m", target_up_axis: "y", source: item.source };
}

export function registrationTransform(value: AssetRegistration) {
  const tuple = ({ x, y, z }: { x: number; y: number; z: number }): [number, number, number] => [x, y, z];
  return { position: tuple(value.translation), rotation: tuple(value.rotation), scale: tuple(value.scale) };
}

import type { SpatialGeometry, SpatialObjectType } from "@/shared/types/spatial";

/** Geometry is an exact discriminated union, including nested material fields. */
export function validateSpatialGeometry(value: unknown, type: SpatialObjectType): SpatialGeometry | null {
  if (value === null) return null;
  const fail = (): never => { throw new Error("Invalid geometry: use the exact box/slab/wall fields, positive finite meter dimensions and valid wall material."); };
  const object = (input: unknown): Record<string, unknown> => {
    if (!input || typeof input !== "object" || Array.isArray(input)) return fail();
    return input as Record<string, unknown>;
  };
  const exact = (input: Record<string, unknown>, fields: string[]) => {
    if (Object.keys(input).length !== fields.length || fields.some((key) => !Object.hasOwn(input, key))) fail();
  };
  const dimension = (n: unknown): number => {
    if (typeof n !== "number" || !Number.isFinite(n) || n < 0.000001 || n > 1_000_000) return fail();
    return n;
  };
  const text = (s: unknown, max = 128): string => {
    if (typeof s !== "string" || !s.trim() || s.includes("\0") || s.length > max) return fail();
    return s;
  };
  const g = object(value);
  if (g.kind === "box" && ["building", "room", "rack"].includes(type)) {
    exact(g, ["kind", "width", "depth", "height"]);
    return { kind: "box", width: dimension(g.width), depth: dimension(g.depth), height: dimension(g.height) };
  }
  if (g.kind === "slab" && type === "floor") {
    exact(g, ["kind", "width", "depth", "thickness"]);
    return { kind: "slab", width: dimension(g.width), depth: dimension(g.depth), thickness: dimension(g.thickness) };
  }
  if (g.kind === "wall" && type === "wall") {
    exact(g, ["kind", "length", "height", "thickness", "material"]);
    const m = object(g.material);
    exact(m, ["name", "attenuation_db", "source"]);
    if (m.attenuation_db !== null && (typeof m.attenuation_db !== "number" || !Number.isFinite(m.attenuation_db) || m.attenuation_db < 0 || m.attenuation_db > 100)) fail();
    return { kind: "wall", length: dimension(g.length), height: dimension(g.height), thickness: dimension(g.thickness),
      material: { name: text(m.name, 256), attenuation_db: m.attenuation_db as number | null, source: text(m.source) } };
  }
  return fail();
}

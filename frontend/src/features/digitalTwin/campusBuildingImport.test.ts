import { describe, expect, it } from "vitest";
import type { CampusBuildingRecord } from "@/shared/types/network";
import { diffCampusBuildings, estimateUpsertBytes, toUpsertCampusBuildingInputs } from "./campusBuildingImport";
import { parseCampusGeoJson } from "./campusImportProvider";

const geojson = JSON.stringify({ type: "FeatureCollection", features: [
  { type: "Feature", properties: { building: "yes", name: "Library", campus: "strathmore", "building:material": "brick" },
    geometry: { type: "Polygon", coordinates: [[[36.8, -1.3], [36.8004, -1.3], [36.8004, -1.2996], [36.8, -1.2996], [36.8, -1.3]]] } },
  { type: "Feature", properties: { building: "yes", name: "Hall", campus: "strathmore" },
    geometry: { type: "Polygon", coordinates: [[[36.801, -1.3], [36.8014, -1.3], [36.8014, -1.2996], [36.801, -1.2996], [36.801, -1.3]]] } },
] });

function persisted(input: ReturnType<typeof toUpsertCampusBuildingInputs>[number], overrides: Partial<CampusBuildingRecord> = {}): CampusBuildingRecord {
  return { campus_building_id: `row-${input.building_id}`, network_id: "n", created_at: "2026-09-01T00:00:00Z", updated_at: "2026-09-01T00:00:00Z",
    ...input, wall_material: input.wall_material ?? null, attenuation_db: input.attenuation_db ?? null, source: input.source ?? null, ...overrides };
}

describe("campus building persistence helpers", () => {
  it("maps imported buildings to the exact backend upsert shape", () => {
    const [hall, library] = toUpsertCampusBuildingInputs(parseCampusGeoJson(geojson).buildings);
    expect(Object.keys(library).sort()).toEqual(["attenuation_db", "base_y", "building_id", "building_key", "campus_key", "depth", "floors", "footprint",
      "geometry", "height", "label", "source", "wall_material", "width", "x", "z"]);
    expect(library).toMatchObject({ building_id: "strathmore:library", wall_material: "brick", attenuation_db: 10, source: "geojson", geometry: "box" });
    expect(hall.building_id).toBe("strathmore:hall");
  });

  it("classifies added, changed, unchanged and removed buildings for the confirm dialog", () => {
    const incoming = toUpsertCampusBuildingInputs(parseCampusGeoJson(geojson).buildings);
    const [hall, library] = incoming;
    const existing = [
      persisted(library),
      persisted(hall, { height: hall.height + 2, label: "Old Hall" }),
      persisted({ ...library, building_id: "strathmore:annex", building_key: "annex", label: "Annex" }),
    ];
    const diff = diffCampusBuildings(existing, incoming);
    expect(diff.unchanged.map((item) => item.id)).toEqual(["strathmore:library"]);
    expect(diff.changed).toEqual([{ id: "strathmore:hall", label: "Hall", fields: ["label", "height"] }]);
    expect(diff.removed.map((item) => item.id)).toEqual(["strathmore:annex"]);
    expect(diff.added).toEqual([]);
    expect(diffCampusBuildings([], incoming).added.map((item) => item.id)).toEqual(["strathmore:hall", "strathmore:library"]);
  });

  it("estimates the UTF-8 request size including the replace flag", () => {
    const incoming = toUpsertCampusBuildingInputs(parseCampusGeoJson(geojson).buildings);
    expect(estimateUpsertBytes(incoming, true)).toBe(new TextEncoder().encode(JSON.stringify({ buildings: incoming, replace_existing: true })).byteLength);
  });
});

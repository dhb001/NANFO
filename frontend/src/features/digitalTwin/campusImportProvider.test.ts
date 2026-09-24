import { describe, expect, it, vi } from "vitest";
import {
  DETERMINISTIC_CAMPUS_IMPORT_PROVIDER,
  EARTH_MEAN_RADIUS_M,
  MAX_CAMPUS_FEATURES,
  MAX_CAMPUS_GEOJSON_BYTES,
  mapImportedBuildingsToCampusBuildings,
  mapPersistedCampusBuildingRecordsToCampusBuildings,
  parseCampusGeoJson,
  parseCampusGeoJsonFile,
  projectLonLat,
} from "@/features/digitalTwin/campusImportProvider";

type Ring = Array<[number, number]>;
const rect = (lon: number, lat: number, dLon: number, dLat: number): Ring => [[lon, lat], [lon + dLon, lat], [lon + dLon, lat + dLat], [lon, lat + dLat], [lon, lat]];
const feature = (name: string, ring: Ring, properties: Record<string, unknown> = {}) => ({
  type: "Feature", properties: { building: "yes", name, campus: "strathmore", ...properties }, geometry: { type: "Polygon", coordinates: [ring] },
});
const collection = (...features: unknown[]) => JSON.stringify({ type: "FeatureCollection", features });
const metresPerDegree = (Math.PI / 180) * EARTH_MEAN_RADIUS_M;
import type { CampusBuildingRecord } from "@/shared/types/network";

describe("campusImportProvider", () => {
  it("parses GeoJSON building features into deterministic campus buildings", () => {
    const parsed = parseCampusGeoJson(
      JSON.stringify({
        type: "FeatureCollection",
        features: [
          {
            type: "Feature",
            properties: {
              building: "yes",
              name: "Engineering Block",
              campus: "strathmore",
              "building:levels": "3",
              "building:material": "concrete",
            },
            geometry: {
              type: "Polygon",
              coordinates: [
                [
                  [36.8000, -1.3000],
                  [36.8010, -1.3000],
                  [36.8010, -1.2990],
                  [36.8000, -1.2990],
                  [36.8000, -1.3000],
                ],
              ],
            },
          },
        ],
      }),
    );

    expect(DETERMINISTIC_CAMPUS_IMPORT_PROVIDER.id).toBe("deterministic.geojson.osm.v2-local-metric");
    expect(parsed.summary).toMatchObject({
      source: "geojson",
      featureCount: 1,
      buildingCount: 1,
      ignoredCount: 0,
      warnings: [],
      projection: { kind: "local-equirectangular" },
    });
    expect(parsed.summary.projection?.originLon).toBeCloseTo(36.8005, 6);
    expect(parsed.summary.projection?.originLat).toBeCloseTo(-1.2995, 6);

    const [building] = parsed.buildings;
    expect(building.id).toBe("strathmore:engineering-block");
    expect(building.campusKey).toBe("strathmore");
    expect(building.buildingKey).toBe("engineering-block");
    expect(building.floors).toBe(3);
    expect(building.geometry).toBe("box");
    expect(building.wallMaterial).toBe("concrete");
    expect(building.attenuationDb).toBe(14);
    // 0.001° on each axis at latitude -1.2995°: metres, not a fixed 80-unit normalisation.
    expect(building.width).toBeCloseTo(0.001 * metresPerDegree * Math.cos((-1.2995 * Math.PI) / 180), 3);
    expect(building.depth).toBeCloseTo(0.001 * metresPerDegree, 3);
    expect(building.footprint).toHaveLength(4);
    expect(building.x).toBeCloseTo(0, 6);
    expect(building.z).toBeCloseTo(0, 6);
  });

  it("projects about the dataset centroid with east = +x and north = -z", () => {
    const parsed = parseCampusGeoJson(collection(
      feature("West", rect(36.8, -1.3, 0.0002, 0.0002)),
      feature("East", rect(36.802, -1.3, 0.0002, 0.0002)),
      feature("North", rect(36.801, -1.298, 0.0002, 0.0002)),
    ));
    const byKey = Object.fromEntries(parsed.buildings.map((building) => [building.buildingKey, building]));
    expect(byKey.east.x - byKey.west.x).toBeCloseTo(0.002 * metresPerDegree * Math.cos((parsed.summary.projection!.originLat * Math.PI) / 180), 1);
    expect(byKey.north.z).toBeLessThan(byKey.west.z);
    expect(byKey.north.z - byKey.west.z).toBeCloseTo(-0.002 * metresPerDegree, 1);
    const origin = parsed.summary.projection!;
    expect(projectLonLat(origin.originLon, origin.originLat, origin.originLon, origin.originLat)).toEqual([0, 0]);
    expect(projectLonLat(origin.originLon, origin.originLat + 1, origin.originLon, origin.originLat)[1]).toBeCloseTo(-metresPerDegree, 3);
  });

  it("keeps backend-owned values within backend limits without narrower client clamps", () => {
    const parsed = parseCampusGeoJson(collection(
      feature("Tower", rect(36.8, -1.3, 0.003, 0.0001), { "building:levels": "40", attenuation_db: 60, height: "130 m" }),
      feature("Odd", rect(36.801, -1.3, 0.0001, 0.0001), { "building:levels": "400", attenuation_db: 95 }),
    ));
    const byKey = Object.fromEntries(parsed.buildings.map((building) => [building.buildingKey, building]));
    expect(byKey.tower.floors).toBe(40);
    expect(byKey.tower.attenuationDb).toBe(60);
    expect(byKey.tower.height).toBe(130);
    expect(byKey.tower.width).toBeGreaterThan(300);
    expect(byKey.odd.floors).toBe(1);
    expect(byKey.odd.attenuationDb).toBeNull();
    expect(parsed.summary.warnings).toEqual([
      "1 floor counts outside 1–128 were replaced by 1",
      "1 attenuation values outside 0–80 dB were dropped (unknown)",
    ]);
  });

  it("extrudes rotated footprints instead of drawing an axis-aligned box", () => {
    const rotated: Ring = [[36.8, -1.3], [36.8003, -1.2997], [36.8, -1.2994], [36.7997, -1.2997], [36.8, -1.3]];
    const [building] = parseCampusGeoJson(collection(feature("Diamond", rotated))).buildings;
    expect(building.geometry).toBe("extrude");
    expect(building.footprint).toHaveLength(4);
  });

  it("ignores non-WGS84 coordinates and rejects country-scale extracts", () => {
    const projected = parseCampusGeoJson(collection(feature("Projected", [[500000, 9800000], [500100, 9800000], [500100, 9800100], [500000, 9800000]])));
    expect(projected.buildings).toHaveLength(0);
    expect(projected.summary.warnings).toEqual(["1 features without a valid WGS84 polygon ring were ignored"]);
    expect(() => parseCampusGeoJson(collection(feature("A", rect(36.8, -1.3, 0.001, 0.001)), feature("B", rect(37.5, -1.3, 0.001, 0.001)))))
      .toThrow("spans more than 25 km");
  });

  it("enforces the feature cap before processing any feature", () => {
    const features = Array.from({ length: MAX_CAMPUS_FEATURES + 1 }, () => ({ type: "Feature" }));
    const every = vi.spyOn(Array.prototype, "entries");
    expect(() => parseCampusGeoJson(JSON.stringify({ type: "FeatureCollection", features }))).toThrow(`at most ${MAX_CAMPUS_FEATURES}`);
    expect(every).not.toHaveBeenCalled();
    every.mockRestore();
  });

  it("checks file type and size before reading the file", async () => {
    const text = vi.fn(async () => collection());
    const big = { name: "campus.geojson", type: "application/geo+json", size: MAX_CAMPUS_GEOJSON_BYTES + 1, text } as unknown as File;
    await expect(parseCampusGeoJsonFile(big)).rejects.toThrow("exceeds 8 MiB");
    await expect(parseCampusGeoJsonFile({ ...big, name: "campus.kml", type: "application/vnd.google-earth.kml+xml", size: 10 } as unknown as File)).rejects.toThrow(".geojson or .json");
    expect(text).not.toHaveBeenCalled();
    const ok = { name: "campus.geojson", type: "", size: 100, text: async () => collection(feature("Hall", rect(36.8, -1.3, 0.0005, 0.0005))) } as unknown as File;
    expect((await parseCampusGeoJsonFile(ok)).buildings).toHaveLength(1);
  });

  it("deduplicates buildings by deterministic id and tracks ignored features", () => {
    const parsed = parseCampusGeoJson(
      JSON.stringify({
        type: "FeatureCollection",
        features: [
          {
            type: "Feature",
            properties: {
              building: "yes",
              name: "Library",
              campus: "strathmore",
            },
            geometry: {
              type: "Polygon",
              coordinates: [
                [
                  [36.80, -1.30],
                  [36.81, -1.30],
                  [36.81, -1.29],
                  [36.80, -1.29],
                  [36.80, -1.30],
                ],
              ],
            },
          },
          {
            type: "Feature",
            properties: {
              building: "yes",
              name: "Library",
              campus: "strathmore",
            },
            geometry: {
              type: "Polygon",
              coordinates: [
                [
                  [36.82, -1.30],
                  [36.83, -1.30],
                  [36.83, -1.29],
                  [36.82, -1.29],
                  [36.82, -1.30],
                ],
              ],
            },
          },
        ],
      }),
    );

    expect(parsed.summary.featureCount).toBe(2);
    expect(parsed.summary.buildingCount).toBe(1);
    expect(parsed.summary.ignoredCount).toBe(1);
    expect(parsed.buildings[0].id).toBe("strathmore:library");
  });

  it("maps imported and persisted buildings into campus-building render records", () => {
    const importedMapped = mapImportedBuildingsToCampusBuildings([
      {
        id: "campus-a:building-1",
        campusKey: "campus-a",
        buildingKey: "building-1",
        label: "Building 1",
        geometry: "box",
        x: 1,
        z: 2,
        baseY: -2.3,
        width: 8,
        depth: 6,
        height: 7,
        floors: 2,
        footprint: [
          [-4, -3],
          [4, -3],
          [4, 3],
          [-4, 3],
        ],
        wallMaterial: "brick",
        attenuationDb: 10,
        source: "geojson",
      },
    ]);

    expect(importedMapped).toHaveLength(1);
    expect(importedMapped[0].metadata.floorKeys).toEqual(["f01", "f02"]);
    expect(importedMapped[0].metadata.wallMaterial).toBe("brick");

    const persistedRecord: CampusBuildingRecord = {
      campus_building_id: "00000000-0000-0000-0000-000000000001",
      network_id: "00000000-0000-0000-0000-000000000002",
      building_id: "campus-a:building-2",
      campus_key: "campus-a",
      building_key: "building-2",
      label: "Building 2",
      geometry: "extrude",
      x: 3,
      z: -2,
      base_y: -2.3,
      width: 10,
      depth: 9,
      height: 9,
      floors: 3,
      footprint: [
        [-5, -4],
        [5, -4],
        [5, 4],
        [-5, 4],
      ],
      wall_material: "glass",
      attenuation_db: 4,
      source: "geojson",
      created_at: "2026-09-02T00:00:00Z",
      updated_at: "2026-09-02T00:00:00Z",
    };

    const persistedMapped = mapPersistedCampusBuildingRecordsToCampusBuildings([persistedRecord]);
    expect(persistedMapped).toHaveLength(1);
    expect(persistedMapped[0].id).toBe("campus-a:building-2");
    expect(persistedMapped[0].geometry).toBe("extrude");
    expect(persistedMapped[0].metadata.attenuationDb).toBe(4);
    expect(persistedMapped[0].metadata.floorKeys).toEqual(["f01", "f02", "f03"]);
  });
});

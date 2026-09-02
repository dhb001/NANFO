import { describe, expect, it } from "vitest";
import {
  DETERMINISTIC_CAMPUS_IMPORT_PROVIDER,
  mapImportedBuildingsToCampusBuildings,
  mapPersistedCampusBuildingRecordsToCampusBuildings,
  parseCampusGeoJson,
} from "@/features/digitalTwin/campusImportProvider";
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

    expect(DETERMINISTIC_CAMPUS_IMPORT_PROVIDER.id).toBe("deterministic.geojson.osm.v1");
    expect(parsed.summary).toEqual({
      source: "geojson",
      featureCount: 1,
      buildingCount: 1,
      ignoredCount: 0,
    });

    const [building] = parsed.buildings;
    expect(building.id).toBe("strathmore:engineering-block");
    expect(building.campusKey).toBe("strathmore");
    expect(building.buildingKey).toBe("engineering-block");
    expect(building.floors).toBe(3);
    expect(building.geometry).toBe("box");
    expect(building.wallMaterial).toBe("concrete");
    expect(building.attenuationDb).toBe(14);
    expect(building.width).toBeGreaterThan(0);
    expect(building.depth).toBeGreaterThan(0);
    expect(building.footprint.length).toBeGreaterThanOrEqual(3);
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

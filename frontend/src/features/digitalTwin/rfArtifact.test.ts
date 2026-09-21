import { webcrypto } from "node:crypto";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MAX_RF_BYTES, parseRFArtifact, pythonCanonical, rfSpatialHash } from "./rfArtifact";
import { rfFixture, rfFixtureScene } from "./rfFixture.test-data";

describe("backend RF artifact boundary", () => {
  beforeEach(() => vi.stubGlobal("crypto", webcrypto));
  afterEach(() => vi.unstubAllGlobals());
  const parse = (value: unknown, scene = rfFixtureScene, frame = "rf-z-up", network = "network-1") => parseRFArtifact(JSON.stringify(value), scene, "workspace-1", network, frame);
  it("verifies actual Python CLI hashes and converts explicit RF XYZ back to network XZY with sign", async () => {
    expect(await rfSpatialHash(rfFixtureScene)).toBe(rfFixture.provenance.spatial_document_sha256);
    expect(await parse(rfFixture)).toMatchObject({ position: [9, 4, 8], signalDbm: -49.0520080561155, uncertaintyDb: null, receiverId: "rx-1" });
    expect(await parse(rfFixture, { ...rfFixtureScene, objects: [...rfFixtureScene.objects].reverse() })).toMatchObject({ position: [9, 4, 8] });
    expect(pythonCanonical({ x: 1e-7, y: -0, name: "é😀", revision: 4 })).toBe('{"name":"\\u00e9\\ud83d\\ude00","revision":4,"x":1e-07,"y":-0.0}');
  });
  it("rejects direct RF results, fabricated fields, nonfinite/bounded inputs and promoted safety/congestion", async () => {
    for (const value of [rfFixture.evaluation, { ...rfFixture, extra: 1 },
      { ...rfFixture, evaluation: { ...rfFixture.evaluation, signal_dbm: "-49" } },
      { ...rfFixture, evaluation: { ...rfFixture.evaluation, signal_dbm: 1e100 } },
      { ...rfFixture, evaluation: { ...rfFixture.evaluation, physical_safety_authorized: true } },
      { ...rfFixture, evaluation: { ...rfFixture.evaluation, congestion: 0.5 } },
    ]) await expect(parse(value)).rejects.toThrow();
    await expect(parseRFArtifact(" ".repeat(MAX_RF_BYTES + 1), rfFixtureScene, "workspace-1", "network-1", "rf-z-up")).rejects.toThrow("1 MiB");
  });
  it("retains explicit assumed uncertainty with hashes from backend CLI, never derives it from congestion", async () => {
    const configHash = "045f7956fcdc3d0eaf6fd65b21b10986cfd730cfddedb4e8735f00844d34cf70";
    const artifact = { ...rfFixture,
      rf_request: { ...rfFixture.rf_request, scene: { ...rfFixture.rf_request.scene, uncertainty_db: 3 } },
      provenance: { ...rfFixture.provenance, adapter_input_sha256: "467c29091d89bb703adedc76d6a60ba826859bdd131e74c944bf9f22fb61b84c", rf_config_sha256: configHash },
      evaluation: { ...rfFixture.evaluation, uncertainty_db: 3, config_sha256: configHash, input_sha256: "28c6f24737d75836a3c1f155b5a0879a677e47c0af446176cc71cfd481f53c98" },
    };
    expect(await parse(artifact)).toMatchObject({ uncertaintyDb: 3, signalDbm: rfFixture.evaluation.signal_dbm });
  });
  it("rejects revision/scene/scope/frame mismatch and edited receiver or config even with unchanged labels", async () => {
    await expect(parse(rfFixture, { ...rfFixtureScene, revision: 5 })).rejects.toThrow("mismatch");
    await expect(parse(rfFixture, rfFixtureScene, "other")).rejects.toThrow("mismatch");
    await expect(parse(rfFixture, rfFixtureScene, "rf-z-up", "other")).rejects.toThrow("mismatch");
    const scene = structuredClone(rfFixtureScene); scene.objects[0].position.x++;
    await expect(parse(rfFixture, scene)).rejects.toThrow("mismatch");
    const changed = structuredClone(rfFixture); changed.rf_request.receiver.x++;
    await expect(parse(changed)).rejects.toThrow("mismatch");
    const config = structuredClone(rfFixture); config.rf_request.scene.frequency_mhz = 5000;
    await expect(parse(config)).rejects.toThrow("mismatch");
    const axes = structuredClone(rfFixture); axes.provenance.axis_conversion = "identity";
    await expect(parse(axes)).rejects.toThrow();
  });
});

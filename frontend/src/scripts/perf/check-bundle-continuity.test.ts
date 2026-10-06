import { describe, expect, it } from "vitest";
import { evaluateContinuityChecks, toContinuitySnapshot } from "./check-bundle-continuity";

describe("VS19 bundle continuity checks", () => {
  it("passes when metrics are within bounded thresholds", () => {
    const checks = evaluateContinuityChecks({
      chunkCount: 26,
      totalJsRawBytes: 1391343,
      totalJsGzipBytes: 407535,
      largestChunkRawBytes: 925193,
      largestChunkGzipBytes: 254576,
      largestChunkFile: "three-CnQjXUib.js",
      largestNonThreeChunkRawBytes: 165161,
      largestNonThreeChunkGzipBytes: 54062,
      largestNonThreeChunkFile: "react-BacFe3xE.js",
      threeChunkRawBytes: 925193,
      threeChunkGzipBytes: 254576,
      twinPageChunkRawBytes: 8035,
      twinPageChunkGzipBytes: 3190,
    });

    expect(checks.total_js_gzip_bounded).toBe(true);
    expect(checks.three_chunk_gzip_bounded).toBe(true);
    expect(checks.largest_non_three_chunk_gzip_bounded).toBe(true);
  });

  it("fails when largest non-three chunk exceeds threshold", () => {
    const checks = evaluateContinuityChecks({
      chunkCount: 26,
      totalJsRawBytes: 1391343,
      totalJsGzipBytes: 407535,
      largestChunkRawBytes: 925193,
      largestChunkGzipBytes: 254576,
      largestChunkFile: "three-CnQjXUib.js",
      largestNonThreeChunkRawBytes: 190001,
      largestNonThreeChunkGzipBytes: 64000,
      largestNonThreeChunkFile: "react-BacFe3xE.js",
      threeChunkRawBytes: 925193,
      threeChunkGzipBytes: 254576,
      twinPageChunkRawBytes: 8035,
      twinPageChunkGzipBytes: 3190,
    });

    expect(checks.total_js_gzip_bounded).toBe(true);
    expect(checks.largest_non_three_chunk_gzip_bounded).toBe(false);
  });

  it("keeps the ADR-028 aggregate cap and fails above it", () => {
    const base = {
      chunkCount: 40, totalJsRawBytes: 1_500_000, totalJsGzipBytes: 432_466, largestChunkRawBytes: 734_055, largestChunkGzipBytes: 192_476,
      largestChunkFile: "three-BekKIdyh.js", largestNonThreeChunkRawBytes: 177_010, largestNonThreeChunkGzipBytes: 58_100,
      largestNonThreeChunkFile: "react--ojjDqGB.js", threeChunkRawBytes: 734_055, threeChunkGzipBytes: 192_476,
      twinPageChunkRawBytes: 1_200, twinPageChunkGzipBytes: 660,
    };
    expect(evaluateContinuityChecks(base).total_js_gzip_bounded).toBe(true);
    expect(evaluateContinuityChecks({ ...base, totalJsGzipBytes: 450_001 }).total_js_gzip_bounded).toBe(false);
  });

  it("emits deterministic snapshot structure", () => {
    const snapshot = toContinuitySnapshot(
      {
        chunkCount: 26,
        totalJsRawBytes: 1391343,
        totalJsGzipBytes: 407535,
        largestChunkRawBytes: 925193,
        largestChunkGzipBytes: 254576,
        largestChunkFile: "three-CnQjXUib.js",
        largestNonThreeChunkRawBytes: 165161,
        largestNonThreeChunkGzipBytes: 54062,
        largestNonThreeChunkFile: "react-BacFe3xE.js",
        threeChunkRawBytes: 925193,
        threeChunkGzipBytes: 254576,
        twinPageChunkRawBytes: 8035,
        twinPageChunkGzipBytes: 3190,
      },
      {
        total_js_gzip_bounded: true,
        largest_chunk_gzip_bounded: true,
        largest_non_three_chunk_gzip_bounded: true,
        three_chunk_gzip_bounded: true,
        twin_page_chunk_gzip_bounded: true,
      },
    );

    expect(snapshot.observed.chunk_count).toBe(26);
    expect(snapshot.observed.largest_chunk_file).toBe("three-CnQjXUib.js");
    expect(snapshot.continuity_limits.total_js_gzip_kb_max).toBeGreaterThan(0);
  });
});

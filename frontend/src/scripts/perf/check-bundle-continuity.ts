import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { gzipSync } from "node:zlib";

export interface BundleContinuityStats {
  chunkCount: number;
  totalJsRawBytes: number;
  totalJsGzipBytes: number;
  largestChunkRawBytes: number;
  largestChunkGzipBytes: number;
  largestChunkFile: string;
  largestNonThreeChunkRawBytes: number;
  largestNonThreeChunkGzipBytes: number;
  largestNonThreeChunkFile: string;
  threeChunkRawBytes: number;
  threeChunkGzipBytes: number;
  twinPageChunkRawBytes: number;
  twinPageChunkGzipBytes: number;
}

export interface BundleContinuityChecks {
  total_js_gzip_bounded: boolean;
  largest_chunk_gzip_bounded: boolean;
  largest_non_three_chunk_gzip_bounded: boolean;
  three_chunk_gzip_bounded: boolean;
  twin_page_chunk_gzip_bounded: boolean;
}

export interface BundleContinuitySnapshot {
  continuity_limits: {
    total_js_gzip_kb_max: number;
    largest_chunk_gzip_kb_max: number;
    largest_non_three_chunk_gzip_kb_max: number;
    three_chunk_gzip_kb_max: number;
    twin_page_chunk_gzip_kb_max: number;
  };
  observed: {
    chunk_count: number;
    total_js_gzip_kb: number;
    largest_chunk_file: string;
    largest_chunk_gzip_kb: number;
    largest_non_three_chunk_file: string;
    largest_non_three_chunk_gzip_kb: number;
    three_chunk_gzip_kb: number;
    twin_page_chunk_gzip_kb: number;
  };
  checks: BundleContinuityChecks;
}

const FRONTEND_ROOT = process.cwd();
const DIST_ASSETS_DIR = path.join(FRONTEND_ROOT, "dist", "assets");

export const CONTINUITY_LIMITS = {
  // Rebaselined for ADR-028 (2026-09-24): the remediation adds required client code in the
  // Twin (+~15 KB gzip: reviewed group/building dialogs, backend-alert severity, virtualized
  // combobox, 2D fallback, instancing/labels) and the platform (+~14 KB: WebSocket C1
  // transport, session recovery/duplicate-tab handling, burst batching, contract/status
  // maps, intent C3 identities, autonomy C17/C25). Measured 432,466 B; the previous
  // 420,000 B cap kept the same ~4% headroom over its baseline. Per-chunk caps are unchanged.
  totalJsGzipBytesMax: 450000,
  largestChunkGzipBytesMax: 260000,
  largestNonThreeChunkGzipBytesMax: 60000,
  threeChunkGzipBytesMax: 260000,
  twinPageChunkGzipBytesMax: 7000,
} as const;

function toKb(bytes: number) {
  return Number((bytes / 1024).toFixed(2));
}

export function collectJsBundleStats(distAssetsDir = DIST_ASSETS_DIR): BundleContinuityStats {
  const jsFiles = readdirSync(distAssetsDir).filter((fileName) => fileName.endsWith(".js"));

  const initial: BundleContinuityStats = {
    chunkCount: jsFiles.length,
    totalJsRawBytes: 0,
    totalJsGzipBytes: 0,
    largestChunkRawBytes: 0,
    largestChunkGzipBytes: 0,
    largestChunkFile: "",
    largestNonThreeChunkRawBytes: 0,
    largestNonThreeChunkGzipBytes: 0,
    largestNonThreeChunkFile: "",
    threeChunkRawBytes: 0,
    threeChunkGzipBytes: 0,
    twinPageChunkRawBytes: 0,
    twinPageChunkGzipBytes: 0,
  };

  return jsFiles.reduce((stats, fileName) => {
    const assetPath = path.join(distAssetsDir, fileName);
    const assetBuffer = readFileSync(assetPath);
    const rawBytes = assetBuffer.length;
    const gzipBytes = gzipSync(assetBuffer).length;

    stats.totalJsRawBytes += rawBytes;
    stats.totalJsGzipBytes += gzipBytes;

    if (rawBytes > stats.largestChunkRawBytes) {
      stats.largestChunkRawBytes = rawBytes;
      stats.largestChunkGzipBytes = gzipBytes;
      stats.largestChunkFile = fileName;
    }

    if (!fileName.startsWith("three-") && rawBytes > stats.largestNonThreeChunkRawBytes) {
      stats.largestNonThreeChunkRawBytes = rawBytes;
      stats.largestNonThreeChunkGzipBytes = gzipBytes;
      stats.largestNonThreeChunkFile = fileName;
    }

    if (fileName.startsWith("three-")) {
      stats.threeChunkRawBytes += rawBytes;
      stats.threeChunkGzipBytes += gzipBytes;
    }

    if (fileName.startsWith("TwinPage-")) {
      stats.twinPageChunkRawBytes += rawBytes;
      stats.twinPageChunkGzipBytes += gzipBytes;
    }

    return stats;
  }, initial);
}

export function evaluateContinuityChecks(stats: BundleContinuityStats): BundleContinuityChecks {
  return {
    total_js_gzip_bounded: stats.totalJsGzipBytes <= CONTINUITY_LIMITS.totalJsGzipBytesMax,
    largest_chunk_gzip_bounded: stats.largestChunkGzipBytes <= CONTINUITY_LIMITS.largestChunkGzipBytesMax,
    largest_non_three_chunk_gzip_bounded:
      stats.largestNonThreeChunkGzipBytes <= CONTINUITY_LIMITS.largestNonThreeChunkGzipBytesMax,
    three_chunk_gzip_bounded: stats.threeChunkGzipBytes <= CONTINUITY_LIMITS.threeChunkGzipBytesMax,
    twin_page_chunk_gzip_bounded: stats.twinPageChunkGzipBytes <= CONTINUITY_LIMITS.twinPageChunkGzipBytesMax,
  };
}

export function getFailedChecks(checks: BundleContinuityChecks): string[] {
  return Object.entries(checks)
    .filter(([, passed]) => !passed)
    .map(([name]) => name);
}

export function toContinuitySnapshot(
  stats: BundleContinuityStats,
  checks: BundleContinuityChecks,
): BundleContinuitySnapshot {
  return {
    continuity_limits: {
      total_js_gzip_kb_max: toKb(CONTINUITY_LIMITS.totalJsGzipBytesMax),
      largest_chunk_gzip_kb_max: toKb(CONTINUITY_LIMITS.largestChunkGzipBytesMax),
      largest_non_three_chunk_gzip_kb_max: toKb(CONTINUITY_LIMITS.largestNonThreeChunkGzipBytesMax),
      three_chunk_gzip_kb_max: toKb(CONTINUITY_LIMITS.threeChunkGzipBytesMax),
      twin_page_chunk_gzip_kb_max: toKb(CONTINUITY_LIMITS.twinPageChunkGzipBytesMax),
    },
    observed: {
      chunk_count: stats.chunkCount,
      total_js_gzip_kb: toKb(stats.totalJsGzipBytes),
      largest_chunk_file: stats.largestChunkFile,
      largest_chunk_gzip_kb: toKb(stats.largestChunkGzipBytes),
      largest_non_three_chunk_file: stats.largestNonThreeChunkFile,
      largest_non_three_chunk_gzip_kb: toKb(stats.largestNonThreeChunkGzipBytes),
      three_chunk_gzip_kb: toKb(stats.threeChunkGzipBytes),
      twin_page_chunk_gzip_kb: toKb(stats.twinPageChunkGzipBytes),
    },
    checks,
  };
}

export function runBundleContinuityCli() {
  const stats = collectJsBundleStats();
  const checks = evaluateContinuityChecks(stats);
  const snapshot = toContinuitySnapshot(stats, checks);
  const failures = getFailedChecks(checks);

  console.log("[perf:bundle] VS19 continuity snapshot");
  console.log(JSON.stringify(snapshot, null, 2));

  if (failures.length > 0) {
    console.error("[perf:bundle] VS19 continuity checks failed:", failures.join(", "));
    process.exitCode = 1;
    return;
  }

  console.log("[perf:bundle] VS19 continuity checks passed");
}

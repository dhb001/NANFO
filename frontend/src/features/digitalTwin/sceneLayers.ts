import type { TwinLink, TwinOverlayObject } from "./sceneAdapter";
import type { RFSample } from "./rfArtifact";
import type { SceneLabelSpec } from "./sceneLabels";
import { overlayLifecycleValue } from "./twinStatusTones";

export const MAX_SCENE_OVERLAYS = 160;
export const MAX_LAYER_LABELS = 24;

/** Line-segment vertex buffer (source, target per link) without intermediate arrays. */
export function linkSegmentPositions(links: readonly TwinLink[]): Float32Array {
  const positions = new Float32Array(links.length * 6);
  links.forEach((link, index) => {
    positions.set(link.source, index * 6);
    positions.set(link.target, index * 6 + 3);
  });
  return positions;
}

/** Deterministic, bounded link labels (by link id). */
export function linkLabelSpecs(links: readonly TwinLink[], limit: number): SceneLabelSpec[] {
  return [...links]
    .sort((left, right) => (left.id < right.id ? -1 : left.id > right.id ? 1 : 0))
    .slice(0, Math.max(0, limit))
    .map((link) => ({
      id: link.id,
      position: [(link.source[0] + link.target[0]) / 2, (link.source[1] + link.target[1]) / 2, (link.source[2] + link.target[2]) / 2] as const,
      text: link.edgeType,
      variant: "link" as const,
      distanceFactor: 30,
    }));
}

export function overlayLabelSpecs(overlays: readonly TwinOverlayObject[], limit = MAX_LAYER_LABELS): SceneLabelSpec[] {
  return overlays.slice(0, Math.min(limit, MAX_SCENE_OVERLAYS)).map((overlay) => ({
    id: overlay.id,
    position: [overlay.x, overlay.y, overlay.z] as const,
    text: `${overlay.objectType} ${overlayLifecycleValue(overlay) ?? ""}`.trim(),
    variant: "overlay" as const,
    distanceFactor: 18,
  }));
}

export function rfLabelSpecs(samples: readonly RFSample[], limit = MAX_LAYER_LABELS): SceneLabelSpec[] {
  return samples.slice(0, limit).map((sample) => ({
    id: sample.receiverId,
    position: sample.position,
    text: `RF modeled ${sample.receiverId}: ${sample.signalDbm.toFixed(1)} dBm · ${sample.uncertaintyDb === null ? "uncertainty unknown" : `assumed ±${sample.uncertaintyDb} dB`}`,
    variant: "rf" as const,
    distanceFactor: 18,
  }));
}

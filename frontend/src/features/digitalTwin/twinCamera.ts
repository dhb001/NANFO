/**
 * Camera clipping and orbit limits for the Twin, derived from the scene content.
 *
 * R3F applies `<Canvas camera={…}>` only when the camera is created, so near/far are
 * pushed imperatively (see `CameraClipController`) whenever these values change. The
 * orbit zoom-out limit is always inside the far plane, so content can never be zoomed
 * past the clipping distance.
 */

export interface CameraClip {
  near: number;
  far: number;
  minDistance: number;
  maxDistance: number;
}

/** Smallest content radius used for limits (schematic layouts span roughly ±20 m). */
export const MIN_CONTENT_RADIUS_M = 40;
export const MIN_FAR_M = 2000;

type Point = readonly [number, number, number];

export function contentRadius({ points = [], boxes = [] }: {
  points?: Iterable<Point>;
  boxes?: Iterable<{ min: Point; max: Point }>;
}): number {
  let radius = 0;
  for (const [x, y, z] of points) if (Number.isFinite(x) && Number.isFinite(y) && Number.isFinite(z)) radius = Math.max(radius, Math.hypot(x, y, z));
  for (const { min, max } of boxes) {
    const cx = Math.max(Math.abs(min[0]), Math.abs(max[0])), cy = Math.max(Math.abs(min[1]), Math.abs(max[1])), cz = Math.max(Math.abs(min[2]), Math.abs(max[2]));
    if (Number.isFinite(cx) && Number.isFinite(cy) && Number.isFinite(cz)) radius = Math.max(radius, Math.hypot(cx, cy, cz));
  }
  return radius;
}

/**
 * `closeUp` (a selected device) allows a much smaller near plane so the device is not
 * clipped when inspected closely; otherwise near keeps a 1:20000 depth ratio.
 */
export function resolveCameraClip(radius: number, closeUp: boolean): CameraClip {
  const bounded = Math.max(MIN_CONTENT_RADIUS_M, Number.isFinite(radius) ? radius : 0);
  const maxDistance = bounded * 4;
  // At the zoom-out limit the far side of the content (distance + radius) stays visible.
  const far = Math.max(MIN_FAR_M, (maxDistance + bounded) * 1.5);
  const near = closeUp ? Math.max(0.01, far / 1_000_000) : Math.max(0.05, far / 20_000);
  return { near, far, minDistance: Math.max(1, near * 10), maxDistance };
}

/** Clamp an orbit distance into the camera's limits. */
export function clampOrbitDistance(distance: number, clip: Pick<CameraClip, "minDistance" | "maxDistance">): number {
  if (!Number.isFinite(distance)) return clip.maxDistance;
  return Math.min(clip.maxDistance, Math.max(clip.minDistance, distance));
}

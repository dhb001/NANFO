import { useEffect } from "react";
import { useThree } from "@react-three/fiber";
import type { PerspectiveCamera } from "three";
import type { CameraClip } from "./twinCamera";

/** R3F applies `<Canvas camera>` props only at creation: push clip changes imperatively. */
export function CameraClipController({ clip }: { clip: Pick<CameraClip, "near" | "far"> }) {
  const camera = useThree((state) => state.camera);
  const invalidate = useThree((state) => state.invalidate);
  useEffect(() => {
    const perspective = camera as PerspectiveCamera;
    if (perspective.near === clip.near && perspective.far === clip.far) return;
    perspective.near = clip.near;
    perspective.far = clip.far;
    perspective.updateProjectionMatrix();
    invalidate();
  }, [camera, clip.near, clip.far, invalidate]);
  return null;
}

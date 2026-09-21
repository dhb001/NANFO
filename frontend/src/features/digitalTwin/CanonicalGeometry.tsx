import { DoubleSide, Vector3, type Plane } from "three";
import type { GeometryShape } from "./spatialGeometry";
import { SceneLabel } from "./SceneLabel";

const noRaycast = () => {};
export function CanonicalGeometry({ shapes, clippingPlanes, showLabels }: { shapes: GeometryShape[]; clippingPlanes: Plane[]; showLabels: boolean }) {
  return <group name="canonical-geometry">{shapes.map(({ object, matrix, size, center }, index) => {
    const shell = object.object_type === "building" || object.object_type === "room";
    const material = object.geometry?.kind === "wall" ? object.geometry.material : null;
    return <group key={object.object_id} matrix={matrix} matrixAutoUpdate={false}>
      <mesh name={`canonical:${object.object_id}`} position={center} raycast={noRaycast}>
        <boxGeometry args={size} />
        <meshStandardMaterial color={shell ? "#47889c" : material ? "#b08462" : "#86928a"} side={DoubleSide}
          transparent opacity={shell ? 0.12 : 0.65} depthWrite={!shell} clippingPlanes={clippingPlanes} />
      </mesh>
      {showLabels && index < 24 && clippingPlanes.every((plane) => plane.distanceToPoint(new Vector3(center[0], size[1], center[2]).applyMatrix4(matrix)) >= 0) ? <SceneLabel position={[center[0], size[1], center[2]]} distanceFactor={30}>
        <div data-geometry-label={object.object_id} style={{ background: "#fff", color: "#263b38", fontSize: 11, whiteSpace: "nowrap" }}>
          {object.name}{material ? ` · ${material.name} · ${material.attenuation_db === null ? "attenuation unknown" : `${material.attenuation_db} dB`} · ${material.source}` : ""}
        </div>
      </SceneLabel> : null}
    </group>;
  })}</group>;
}

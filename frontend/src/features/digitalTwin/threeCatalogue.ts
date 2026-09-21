// Fiber's Canvas registers these JSX constructors in production. Imported glTF
// objects use <primitive> and retain GLTFLoader's own full set of dependencies.
export {
  AmbientLight,
  ArrowHelper,
  BoxGeometry,
  ConeGeometry,
  CylinderGeometry,
  DirectionalLight,
  ExtrudeGeometry,
  Group,
  IcosahedronGeometry,
  InstancedMesh,
  LineBasicMaterial,
  LineSegments,
  Mesh,
  MeshBasicMaterial,
  MeshStandardMaterial,
  OctahedronGeometry,
  RingGeometry,
  SphereGeometry,
} from "three";

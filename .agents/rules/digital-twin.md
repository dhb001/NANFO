---
match: "frontend/**"
---

# Digital Twin Architecture

## 1. Core Digital Twin Philosophy
* **Never Hardcode:** The renderer must never contain embedded knowledge of specific buildings, campuses, or device placements; it must dynamically read structured JSON data from the Unified Enterprise Data Fabric (UEDF) to draw the scene.
* **Everything is Data:** Every element (walls, trees, access points, users, packets) is an explicitly defined data object inheriting from the Universal Object Model (UOM).
* **Rendering is Not Data Storage:** The 3D renderer does not store system state; it acts purely as a visual consumer of the backend API.
* **The Twin is Alive:** Real-time telemetry, AI recommendations, and packet animations must update continuously via WebSocket delta payloads without requiring a page refresh.

## 2. Spatial Object Hierarchy
Every element rendered on screen must strictly organize into the following spatial hierarchy to ensure absolute spatial awareness:
* Scene → Campus → Terrain → Road → Building → Floor → Room → Rack → Device → Interface → Coverage Cell → Client.

## 3. Game-Engine Rendering Pipeline
To maintain 60 FPS performance in massive enterprise environments, the React Three Fiber execution loop must process spatial data through this strict sequence:
1. **Scene Graph Construction:** Query the UEDF and construct the hierarchical tree.
2. **LOD & Culling Manager:** Execute aggressive Frustum Culling (ignoring objects outside the camera view) and Occlusion Culling (ignoring objects hidden by walls). Utilize Level of Detail (LOD) swapping to simplify distant structures into 2D billboards.
3. **Lighting & Material Pass:** Compute physical rendering properties and material transparency (e.g., for RF attenuation models).
4. **Picking Engine (Raycasting):** Process user interactions by mathematically tracing a ray through the 3D space to identify exact Network Objects and trigger the UI Context Inspector.
5. **Animation Engine:** Calculate continuous interpolation of moving entities (roaming users, packet spheres).
6. **Overlay Renderer:** Blend volumetric heatmaps (Wi-Fi signals, AI confidence) directly onto the 3D geometry.

## 4. Synchronization & Physics Interface
* **State Synchronization:** Digital Twin state changes must consume domain events and WebSocket deltas; avoid polling-driven redraw loops.
* **Physics Interface Contract:** Simulation outputs (coverage, interference, risk overlays) must be consumed through explicit contracts, not renderer-side assumptions.
* **Topology Representation:** Spatial and logical topology views must remain traceable to the same canonical object IDs.
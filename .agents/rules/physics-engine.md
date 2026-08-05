---
match: "{backend,ai-engine}/**"
---
# Network Physics Engine (NPE) & Simulation Framework

## 1. Simulation Architecture & Principles
* **Predictive Physics:** NPE models expected computational, spatial, and physical behavior before physical deployment.
* **Deterministic Reproducibility:** Randomly-seeded simulation runs must guarantee 100% mathematical reproducibility for academic research and benchmarking.
* **Master Clock Synchronization:** Every tick advances synchronously across execution layers: Update Physics -> Update Network -> Update Wireless -> Update Users -> Update AI -> Render Scene.
* **State Machine:** Simulations must strictly traverse the FSM lifecycle: Draft -> Queued -> Running -> Paused -> Completed -> Cancelled.

## 2. Core Simulation Sub-Engines
* **User Mobility Engine:** Model demand via discrete spatial entities navigating building navigation meshes using role-based movement profiles.
* **RF Engine:** Calculate propagation dynamically based on 3D Digital Twin material attenuation coefficients (glass, drywall, concrete, metal) and AP radiation patterns.
* **Traffic Engine:** Model realistic protocol distributions (VoIP, video streams, bulk transfers) and simulate buffer queue growth, jitter, and packet drops under saturation.

## 3. Branching Scenarios ("Git for Networks")
* Support cloning the active production state into isolated simulation branches (e.g., Branch A: Add 5 APs; Branch B: Upgrade core switch uplinks).
* Evaluate competing futures side-by-side in 3D to compare latency, CAPEX, and AI reward metrics prior to physical deployment.
---
match: "{backend,plugins}/**"
---
# Network Hypervisor & Intent Orchestration

## 1. Core Abstraction Laws
* **Vendor Neutrality:** Abstract and represent hardware capabilities rather than brand names.
* **No Direct Vendor Logic in Core:** Core platform code must never contain hardcoded vendor CLI commands. All vendor mechanics are sandboxed inside isolated Device Drivers within the Device Abstraction Layer (DAL).
* **Universal Network Intent Language (UNIL):** Administrators and AI agents express commands using structured, vendor-neutral UNIL schema declarations (YAML/JSON).

## 2. Intent Processing Pipeline
When a UNIL intent is dispatched, the Hypervisor must execute this strict pipeline:
1. **Capability Matching:** Verify targeted physical devices possess required hardware, firmware, and licenses.
2. **Dependency & Blast-Radius Analysis:** Query Neo4j Knowledge Graph to assess downstream impact.
3. **Simulation & Risk Assessment:** Route intent to Network Physics Engine to project performance impact.
4. **Policy & Approval:** Enforce change freeze policies and request human authorization if confidence is below safety thresholds.
5. **Driver Translation & Execution:** DAL translates UNIL payload into protocol-specific operations (RESTCONF, NETCONF, gNMI, SSH).
6. **Verification & Digital Twin Sync:** Poll post-change telemetry to confirm success, update 3D state, and log to the immutable audit ledger.

## 3. Execution Mechanics & Safeguards
* **Transaction Engine & Native Rollback:** Every configuration push executes as an atomic transaction. If post-change verification fails, the Rollback Engine automatically issues compensating commands to restore the prior configuration version.
* **Device Lifecycle FSM:** Strictly enforce state machine transitions: Provisioning -> Online -> Monitoring -> Warning -> Critical -> Maintenance -> Offline -> Retired.
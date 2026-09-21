# ADR-024: Measured Qualification Campaign

- Status: Accepted under the user's explicit request to complete runtime and native qualification
- Date: 2026-09-20

## Authorization and limits

The user requests completion of the remaining runtime/causal/physical qualification
and retains the isolated-local-lab environment. After clarification the user states
there are **no RF survey files or equipment**. Physical RF qualification is therefore
externally blocked; simulated or emulated measurements must not substitute for it.

Authorize newly owned disposable evaluation/instrumentation labs, native routing
readback/compensation tests and bounded workload acquisition. Serialize privileged
network experiments; never mutate shared services, original artifacts, namespaces,
images/tags or historical qualification. Preserve every failed attempt. Do not change
model weights or train unless recovering the exact matching runtime proves impossible
and a separately documented bounded training protocol is necessary and communicated.

## Matching runtime

First recover preserved v4 source/image artifacts and verify original byte hashes,
model manifest and source provenance. A rebuilt image gets a new recorded identity;
do not relabel it the historical image or bypass source/runtime compatibility checks.
Use an explicitly preregistered fresh operational seed set disjoint from historical
reserved tests for new evaluation. The measured feed bridge must attach before new
measurements; never freshen old records. Exercise actual continuous observation,
confined inference, qualification and durable recommendations using private stores.

## Native execution

Define a narrowly scoped, enforceable lab operating domain before acquisition.
The safety certificate must retain actual units, attribution, plan/egress mapping,
transition/horizon timing, all background traffic and source/runtime pins. Empirical
maxima or passing tests do not prove future service guarantees. If conservative
enforced bounds support only a limited/quiescent operating regime, label it exactly
and do not claim adaptive congested-network operation. A proof about an application
FIFO is not a proof about kernel/FRR queues.

Use the existing independent validator and receiver trust boundary. Software-derived
lab evidence can be independently checked by a separate workstream, but no agent
may impersonate a human attester or fabricate equipment certification. Local software
attestation is explicitly scoped to isolated emulation. Any proof/model limitation
that prevents legitimate installation stays blocked with its raw evidence.

## Campaign deliverables

Versioned operator/verifier scripts, preregistration and exact source/image manifests,
raw measurement logs, independent metric reconstruction, live recommendation and
native readback/recovery outcomes, cleanup ledger, and a concise residual qualification
matrix. Keep calibration/activation flags false until the existing requirements are
actually satisfied. No new public APIs or relaxed safety thresholds are authorized.

## Rebuilt-image qualification amendment

Recovery established exact v4 lab/AI sources but the historical image is absent.
The original frozen loader rejects the truthful rebuilt image identity. Approve a
new derived deployment artifact, preserving original tensor bytes and the original
checkpoint untouched, with explicit parent/weights/source lineage and the actual
rebuilt image binding. This is provenance rebinding, not training or an already
qualified model. Use the unchanged original artifact writer/loader and complete
manifest checks. The derived artifact stays unqualified until a fresh preregistered
five-policy matched campaign on previously unused seeds meets the original scoped
directionality/constant-policy/OSPF criteria with independent raw reconstruction.
Never reuse historical qualification for the new artifact. A versioned registry
protocol may admit the new campaign; original ADR014 support/thresholds stay intact.
No fabricated image ID, monkeypatched loader, changed tensors or retimestamped data.

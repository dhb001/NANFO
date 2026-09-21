# ADR018 Selected Probe Paths

## Operator Use

This diagnostic sends three ICMP echo requests from h1 to h3, not application
traffic and not training. A random window UUID is embedded in each payload;
the ICMP identifier and sequences 1..3 form three correlated packet identities.
Forty direction-specific tcpdump captures cover every switch port and both host
interfaces. The producer uses Mininet's existing host namespaces, never host PID
discovery, backend credentials, or planned routes as observations.

The incumbent image was preserved before any build:

```text
nanfo-emulation:campus-small-v1
nanfo-emulation:adr015-v5
nanfo-emulation:pre-adr018-incumbent
sha256:31c749ef79621fc15e959991f04ab5884f2cb3a16924ad3fc522f74edd3f48d9
```

Only `nanfo-emulation:operator-paths-adr018` was built. Do not use `control.py build`
for this workstream because it targets the default image. Historical checkpoints,
frozen sources and training artifacts were not edited. No training was run.

From the repository root, after confirming no other operator owns the lab:

```bash
docker build -t nanfo-emulation:operator-paths-adr018 emulation
NANFO_EMULATION_IMAGE=nanfo-emulation:operator-paths-adr018 python emulation/control.py start
python emulation/control.py paths
```

The new fixed command reuses `/run/nanfo/control.sock` (mode0600). No remote capture
API, arbitrary host/interface argument, new lab field or snapshot field was added.
Stop only the lab container you started after checking its exact identity. The
verification containers used for this change were stopped/removed, not left active.

## Artifacts And Bounds

- Latest: `output/probe-paths.json`, atomic version1 export.
- Raw: `output/probe-capture-<window UUID>/<allowlisted interface>-<in|out>.pcap`.
- Each successful window also retains `artifact.json` inside its capture directory.
- Three selected packets, <=512 total packet sightings, <=64 capture references,
  <=64KiB per pcap, <=1MiB JSON, <=30s window.
- Eight capture directories maximum. Capture refuses further work at capacity;
  the operator must archive reviewed, owned windows. Nothing auto-deletes another
  operator's evidence. Failed attempts also count toward this bound.
- Evidence includes run/window IDs, source/destination IP and timestamps, ICMP
  ID/sequence, payload and packet hashes, capture record indices, interface names,
  DPID/ingress/egress ports, ordered receive/send times, file sizes and SHA256s.
- A whole-artifact SHA256 covers canonical sorted compact JSON, excluding its own
  `evidence_sha256` field. It is an integrity digest, not a signature or proof that
  a compromised producer cannot forge packets.

Only actual receive/send observations produce hops. Topology describes capture
coverage and validates adjacency; it never fills missing hops. Duplicate identical
sightings deduplicate, distinct repeated/branching sightings remain ambiguous.
Missing interfaces, host delivery or order evidence produce partial results.

## API Handoff

`GET /api/v1/telemetry/paths?network_id=UUID` uses the standard envelope and
`read:telemetry`. See `backend/app/modules/telemetry/paths.py`:
`ProbePathsResponse`, `BoundPath`, `BoundHop`, `CapturedPacket`, `Capture`.

The separate router is `backend/app/api/v1/telemetry_paths.py`. It rechecks the
requester's active network/workspace membership and the binding owner's current
capabilities, writable membership and every bound active device through existing
Network/Identity contracts. Canonical device UUIDs come only from the trusted
operator binding, not hostname guessing. Binding scope mismatch exposes no paths.

No configuration setting is needed beyond existing emulation mode, binding and
snapshot settings. The reader opens only `probe-paths.json` alongside the configured
snapshot and derives raw pcap filenames from its fixed interface allowlist/window.
It refuses symlinks in every path component, bounds all reads, verifies raw hashes,
re-decodes the ICMP packets and reconstructs paths before accepting JSON claims.
Producer file pointers are compared, never used as arbitrary backend read targets.

Response semantics:

- `scope=selected_probe_only` always. No all-flow/current-route inference.
- `status=measured|partial|ambiguous|stale|unavailable|invalid|run_mismatch`.
- `freshness=fresh|stale|unavailable`; freshness is about this measurement window.
- `paths[].status=measured|partial|ambiguous` describes completeness during capture,
  not freshness now. Always inspect top-level freshness before presenting paths.
- Window start/end, run/window IDs, source/destination timestamps and per-hop times
  are retained. `age_seconds` is age of the window end; expiration conservatively
  uses the window start and min(30s, configured snapshot age).
- `measured_path_count` counts complete selected packet paths, including historical
  complete paths in a stale response. It does not mean currently active routes.
- A stale window with a fresh same-run snapshot retains diagnostic evidence with
  `status=stale`. An expired/unavailable snapshot returns no paths and
  `reason=current_snapshot_unavailable`. Different runs return no paths.
- `path_variation=single_observed_path|multiple_observed_paths|unknown` distinguishes
  variation among fully observed probes without claiming all-flow multipath.
- `evidence_verification=raw_pcap_replayed` only after independent raw verification.
- `configuration_comparison=unavailable`: this read-only provider deliberately does
  not query Intent/Autonomy history or represent a desired route as approved state.

Only the latest window is served. Retained capture windows are local operator
evidence, not a new history API. No DB tables, telemetry repository writes,
autonomy queries, learning-source changes or WebSocket contracts were introduced.

## Verification Record

Actual `control.py paths` capture, run
`26dba7ce-0ae7-41a1-8e8f-2f13c35d1aeb`, window
`67e84792-d9d4-495d-8c2c-2a0407eda4b2`: three measured paths, 24 packet sightings,
`access1 -> dist1 -> access2`. The first image build preceded per-window archive
publication; its raw pcaps remain, but that first window has no archived JSON.

The isolated existing-`Lab`/`Actions` verifier then completed baseline, actual
five-switch reroute and exact driver restoration. It did not invoke experiments
or training. Run `b7393de7-4b17-458d-843c-687b019f318a`:

| Phase | Window | Hops Per Probe | Packet Sightings |
| --- | --- | --- | --- |
| Baseline | `62c8d4f1-d1ec-4cc9-a8ce-c9b0835d0b49` | 3,3,3 | 24 |
| Rerouted | `8abc2b87-2a9a-4d1e-b0d5-0be5ee5ddb4f` | 5,5,5 | 36 |
| Restored | `31fa960f-5f69-4156-9c69-c8e889f7170d` | 3,3,3 | 24 |

Rerouted observations: `access1 -> dist1 -> core -> dist2 -> access2`.
Result: `output/probe-paths-verification.json`, `passed=true`. The verifier cleaned
up its container/network. Full source for repeatable verification:
`emulation/verify_probe_paths.py`.

```bash
NANFO_EMULATION_IMAGE=nanfo-emulation:operator-paths-adr018 docker compose -f emulation/compose.yaml run --rm --no-deps --name nanfo-adr018-path-verifier --entrypoint python lab -m emulation.verify_probe_paths
```

Backend tests cover strict schemas, forged JSON success, altered/missing raw pcaps,
symlinked file/parent/binding, tenant mismatch, owner revocation, inactive/foreign
inventory, missing hops, run changes, freshness, current permissions and envelopes.
An opt-in HTTP test replays the real restored capture at its recorded timestamp,
then explicitly advances the fixture clock/current snapshot to verify stale
semantics. This is recorded packet replay, not a claim of live DB-backed tenant
authorization: HTTP tests use persistence fixtures and real authorization logic.

```bash
# From backend/
NANFO_REPLAY_PROBE_CAPTURE=1 PYTHONPATH=..:. poetry run pytest tests/unit/test_telemetry_paths.py tests/integration/test_telemetry_paths_endpoints.py tests/unit/test_emulation.py tests/integration/test_telemetry_endpoints.py -q --no-cov
```

The recorded run of this command passed129 tests; adding the existing Intent lab
regressions passed175 tests. All backend unit tests plus the new HTTP tests passed
1539 tests with3 opt-in skips. Scoped Ruff and `git diff --check` passed. The final
image test gate ran89 tests:87 passed and2 unrelated opt-in live tests skipped.
No shared database/service resets occurred. Final operator image:
`sha256:6d4c5efd8a86` (short ID; inspect Docker for the full digest).

## Busy And Restart Safety Follow-Up

Lab-only fixes after serious review:

- Exact recovered obsolete cancellation now rechecks current run reserved-resource
  absence (or the exact journaled newer active policy), then emits a fresh
  `cancelled` no-mutation receipt. Original run/hash identity remains unchanged;
  original terminal proof is retained as `obsolete_result`. Failed reconciliation
  yields `uncertain`, never a recycled completion proof or destructive rollback.
- Active-policy reconciliation rejects extra reserved flows/groups/meters/queues,
  not just the presence of expected rules. Cancelling an obsolete record never
  removes a newer active policy.
- `capturePaths(lab, service_controls=None)` checkpoints before creating anything,
  between capture starts/stops, during readiness/probe/drain/shutdown waits and
  before publication. Its default services only configured manual mailbox cancels,
  never queued execute commands. Wait slices are50ms (readiness100ms); the control
  handler's own verified rollback/readback duration remains additional latency.
- Callback truth or manual control-generation change interrupts the window;
  `lab.stopping` also interrupts. Runner returns `passed=false,status=partial` and
  does not publish a new artifact. Previous evidence retains its original window.
  Owned children are killed together and reaped within one shared cleanup bound;
  unreaped children remain owned by Lab for final cleanup.

Private live verifier: `emulation/verify_probe_safety.py`, with no shared output,
command/result mount, backend/frontend edit, database use or training. Evidence:
`/tmp/opencode/adr018-probe-safety-output/probe-safety-verification.json`.
Run `b2ecd574-a26f-48d1-a683-5adfd17648b4` passed:

| Check | Actual Result |
| --- | --- |
| Baseline and restored capture | Three complete selected probes,24 sightings each |
| Expiry-style cancel during probes | Verified restoration in0.275826s |
| STOP-style cancel during probes | Verified restoration in0.301944s |
| Interrupted window | Partial, no new artifact, no remaining capture children |
| Obsolete cancellation | Fresh real OVS/TC no-mutation proof, cancelled receipt |

The verifier locally publishes the exact cancel to model worker expiry/STOP;
it does not test the backend timed-override worker or invent lab TTL behavior.
Its obsolete journal state is seeded to simulate restart, then reconciled against
real OVS/TC. Unit tests additionally cover exact completed old-run recovery/cancel,
new active policy preservation, conflicting identity, failed fresh readback,
cancel-only dispatch exclusion and capture checkpoints. Actual process-restart /
backend override integration remains available to the parent workstream.

The private container exited and released the lab. Only
`nanfo-emulation:operator-paths-adr018` was rebuilt; the prior operator image is
preserved as `nanfo-emulation:operator-paths-adr018-pre-safety`. All incumbent/default
aliases remain on `sha256:31c749ef79621fc15e959991f04ab5884f2cb3a16924ad3fc522f74edd3f48d9`.

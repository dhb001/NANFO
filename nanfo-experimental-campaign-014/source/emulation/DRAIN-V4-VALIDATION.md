# ADR-014 Drain V4 Release

Validated 2026-09-10 (local operator date). Scope: `emulation/**` only. No training,
AI/backend/frontend edits, OSPF cost changes, topology changes or outcome-driven
benchmark tuning. One predeclared train-seed smoke per mode, no invalid-run retries.
This is instrumentation validation, not a learned-policy superiority claim.

## Frozen Identity

- Image tag: `nanfo-emulation:campus-small-v1`
- Actual image ID: `sha256:6b4ed91c2e7be7e4fbbb536ad3a808eb0e98c9d5f8165a5008846586893016ff`
- Matched AND OSPF spec hash: `bb15142a19ed3ee87a6aec2c6f9109d789d9736a5e6afda826ad898ef5fe7200`
- Source SHA256: `08c312c64154c9aedcd3b22eeb3573783590e0eb7183bc999cb8ef39b958dbbd`
- Spec version: **4**; outer request/response version: **1**.

The exact new spec fields, raw evidence field names and limitations are in
[EXPERIMENT.md, Verified Drain V4](EXPERIMENT.md#verified-drain-v4-adr-014).
Every raw reset/step includes the full spec and per-file hashes. The smoke compares
the full executing spec/hash to workspace `environmentSpec(mode)` and checks
`provenance.lab_image_id` against `docker inspect ... .Image`, not merely a hash
prefix. Matched and OSPF source/spec identities matched on all six windows.
These are source provenance checks, not remote attestation.

## Verification

- Host: 78 tests run, 72 passed, 6 runtime/opt-in skips.
- Docker build: 78 tests run, 76 passed, 2 opt-in fault/reconvergence skips.
- Ruff check, format check, and scoped whitespace check passed.
- Added regressions: two timed empty sweeps; nonempty-to-empty; empty streak reset;
  nonempty cap timeout; malformed/missing leaf; receiver exit; owned `tc` timeout
  cleanup; invalid drain timing; unverified drain rejects valid loss/goodput while
  retaining endpoint evidence. Old `drain_seconds` is absent; all modes use v4.
- Live: one matched and one OSPF episode, each reset + two decisions, seed 1000,
  stationary `path0`, requested 2-second windows, alternate requested actions.
- Each smoke passed eight protocol rejection checks and acknowledged exact routing
  cleanup. No measurement was truncated. Both initial actor observations are
  complete, including actual offered rate and read-back `[2,20]` capacities.

Matched episode: `5d103ad3-7fe0-4564-a584-a771a454e3ec`.
OSPF episode: `9aec0872-c979-4c01-bb02-d977e6addbc2`.

| Mode/index | Drain begin (monotonic s) | Drain end (monotonic s) | Actual drain s | First sweep packets | Final sweep |
| --- | ---: | ---: | ---: | ---: | --- |
| matched/0 | 13961.29597835 | 13962.108336353 | 0.8123580030005542 | 89 | 22/22 empty |
| matched/1 | 13968.23803234 | 13969.023227987 | 0.7851956470003643 | 89 | 22/22 empty |
| matched/2 | 13973.741377121 | 13974.74575197 | 1.0043748490006692 | 88 | 22/22 empty |
| ospf/0 | 14004.641593348 | 14005.430140651 | 0.7885473030000867 | 88 | 22/22 empty |
| ospf/1 | 14010.592293771 | 14011.384626857 | 0.7923330859994167 | 90 | 22/22 empty |
| ospf/2 | 14015.149912413 | 14016.14693555 | 0.9970231369989051 | 88 | 22/22 empty |

First-sweep sums are actual sampled leaf backlogs, not inferred UDP late delivery
or an atomic topology snapshot. All windows contain two consecutive complete
zero-byte/zero-packet sweeps separated by at least 80ms, both within 3 seconds.
For example, matched reset empty sweeps span
`13961.738208578..13961.883589957` and
`13961.963981306..13962.108263807`. Raw qdisc rows and individual read timestamps
are retained in `queue_begin`, `queue_end`, and `drain_empty_observations`.
`late_received_packets` is `[null,null]` on all windows because workers have no
drain-begin streaming counters. No late-delivery count was invented.

| Mode/index | Foreground sent/received packets | Actual sender s | Goodput Mbps | Loss fraction |
| --- | --- | ---: | ---: | ---: |
| matched/0 | 1659 / 506 | 2.606283851999251 | 1.8638031296068498 | 0.6949969861362266 |
| matched/1 | 2151 / 1927 | 3.3791972500002885 | 5.474436273288995 | 0.10413761041376102 |
| matched/2 | 2151 / 774 | 3.3791962079994846 | 2.19886610384156 | 0.6401673640167365 |
| ospf/0 | 1502 / 468 | 2.359666305999781 | 1.9039980308132674 | 0.6884154460719041 |
| ospf/1 | 1504 / 471 | 2.362788851000005 | 1.913670786996612 | 0.6868351063829787 |
| ospf/2 | 1496 / 463 | 2.350246132000393 | 1.8912061760173366 | 0.6905080213903743 |

Actual post-control windows were 2.099661219..2.127430257 seconds; they were not
substituted for sender denominators. Matched route-switch overhead and transition
loss remain included. OSPF ignored actions and remained on actual route 0.
Latency remains measured ICMP RTT. This tiny smoke cannot establish comparative
policy quality, and historical cutoff counts were not corrected or overwritten.

Raw files in `emulation/output/`:

- `experiment-5d103ad3-7fe0-4564-a584-a771a454e3ec-{00,01,02}.json`
- `experiment-9aec0872-c979-4c01-bb02-d977e6addbc2-{00,01,02}.json`
- `experiment-smoke-matched-5d103ad3-7fe0-4564-a584-a771a454e3ec-summary.json`
- `experiment-smoke-ospf-9aec0872-c979-4c01-bb02-d977e6addbc2-summary.json`
- Existing append-only `experiment-smoke-{matched,ospf}.jsonl` include the new
  complete request/response traces; use episode identity and spec hash to select.

## Release Lifecycle

Executed sequentially, without competing lab ownership:

```bash
python emulation/control.py build
python emulation/control.py experiment-start --mode matched
python -m emulation.experiment_smoke --mode matched --episodes 1 --steps 2 --window 2 --seed 1000 --policy alternate
# Smoke sends close; wait for exact owned container to finish removal.
docker ps -a --filter name=nanfo-experiment --format '{{.ID}} {{.Names}} {{.Status}}'
python emulation/control.py experiment-start --mode ospf
python -m emulation.experiment_smoke --mode ospf --episodes 1 --steps 2 --window 2 --seed 1000 --policy alternate
docker ps -a --filter name=nanfo-experiment --format '{{.ID}} {{.Names}} {{.Status}}'
```

Final inventory returned no experiment container. Both `close` acknowledgements
reported `cleanup_verified:true`; server shutdown removed owned namespaces and
FRR/workload processes with the disposable container. Unrelated containers were
not stopped or modified. The lab slot is released, not left idle for training.

AI handoff must read this exact v4 spec and pin both spec hash and image ID before
collection. Start a fresh `experiment-start --mode matched` or `--mode ospf` owner
for each mode/session; first reset and subsequent requests must arrive within the
300-second idle watchdog. `close` ends the server, not only the episode. Emergency
stop is `python emulation/control.py experiment-stop`, targeting only the owned
`nanfo-experiment`. Do not rebuild merely for handoff: a rebuild can change the
image ID even when measured source/spec hashes are identical. A new source change
requires a new build, source/spec proof and fresh instrument validation.

No PPO run, reserved test access, two-hour collection stage, model selection or
production activation was started by this release. Those remain separate AI-owned
ADR-014 stages with saved plans and caps.

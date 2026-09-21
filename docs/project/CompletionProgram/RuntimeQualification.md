# ADR024 frozen runtime recovery — 2026-09-20

## Final amended campaign outcome — PASS

**First measured campaign passed all preregistered criteria in1475.774seconds**
(1800second cap).60 complete episodes,300 measured reset/step windows,240 reconstructed
decisions; five policies each12 seeds/48 decisions. Zero invalid windows. No campaign
retry, model retuning, tensor change, or training. All five owned containers stopped,
raw lab outputs copied, IDs removed and absence verified. **Exclusive privileged
lab slot is released to parent on this handoff.** Shared services remain running.

| Comparison / criterion | Mean PPO minus baseline | Paired12-seed95%CI | Result |
|---|---:|---:|---|
| Constant0 reward | +1.152972 | [0.383082,1.922862] | Pass >.02, lower>0 |
| Constant1 reward | +1.184229 | [0.391408,1.977051] | Pass >.02, lower>0 |
| OSPF goodput (Mbps) | +1.976736 | [0.664504,3.288967] | Pass lower>0 |
| OSPF ICMP RTT (ms) | -129.316271 | [-217.204961,-41.427581] | Pass upper<0 |
| Heuristic reward (retained comparison) | +0.490170 | [0.144257,0.836083] | Reported |
| Direction path0 impairment → route1 | 24/24 correct | majority required | Pass |
| Direction path1 impairment → route0 | 24/24 correct | majority required | Pass |

Uncertainty is the original paired seed-mean Student-t method; no packet/window
pseudoreplication. Scope remains balanced stationary2/20Mbps impairments versus
unchanged nominal-cost OSPF in isolatedv4 Linux/FRR. This is not capacity-aware OSPF,
physical qualification, a safety certificate, or an autonomous actuation authorization.

### Exact readiness artifacts

Root: `/tmp/opencode/nanfo-adr024-evaluation-002/` (protected, portable relative refs).

| Artifact | SHA256 |
|---|---|
| `checkpoint.ptz` (new deployment artifact) | `77dae44acab722a5a6a2e87d952a6cca65e1c4eea102a089830a8401b521d614` |
| `parent-checkpoint.ptz` (unchanged parent byte copy) | `5b8818af655ec8efce5d3bc3def27db599f3e0df379a0ae263dcefb5f72a80a5` |
| `plan.json` | `b9e084a2c69241d3d5d3e2f60ab3f9052ee77e713befc1f43403fd21de8e4a30` |
| `lineage.json` | `c18cd15bce1dcc2883dc2e5f0c968ab11171e1eef4c4d19cf9531784760a0fb3` |
| `seed-audit.json` | `7313600bd0e01630fc03ce557289be379ff365070ba8b94abca80c99672e7b62` |
| `test-report.json` | `e6ee9c1bd99e3f6961db497db664335684fa277bd1a1c86a8034570ac116056d` |
| `qualification.json` | `65a97c2cca37a354c7de22bffd8a67e700e8b5f11158d8f3f10d7ee5132d9432` |
| `deployment-registry.json` | `2fc1c0ef45ef04ba1a35722bf438cb930591bcb7abc17a610c213350701368dd` |
| `independent-verification.json` | `034788eb679259a55d5300a8695a2a6554b1bc8d9110f189fc0c34780ab6a644` |
| `live-registry.template.json` | `3f7b4b5c614bffe6f2270c41748f7a84981d24d57b38ddbfae538260f86bd8a8` |

`deployment-registry.json` is the portable campaign catalog with exact five-policy
summary/evidence references and source map. `live-registry.template.json` is the
actual backend installation schema, protocol=`adr024-rebuilt-evaluation-v1`, including
parent checkpoint, lineage, seed audit, acquisition attachments, report and all five
sessions. It has no caller-supplied qualified flag. Supply real scope/install/expiry
fields, protect it **outside** the artifact and observation roots and pin final bytes.

Source-matched image remains
`sha256:954462c0f00d5bbaa72ea144f6064936b399c430e6ab94bffcf1c00d134ea0d7`.
Frozen source/spec hashes and exact Python/PyTorch/NumPy/Gymnasium versions below
remain unchanged. `source/`, `campaign-runner.py`, `recovery-runner.py`, all command
logs, five cleanup receipts and five raw `/output` copies are retained in the bundle.

### Independent reconstruction and confined acceptance

`scripts/verify_adr024_campaign.py` reread all raw logs in a fresh process and
reconstructed the entire saved report with the original frozen parser plus actual
derived-PPO action/probability replay. A separate arithmetic implementation recomputed
all four metrics and every paired CI directly from raw measurements and matched to
1e-12. Seed audit covered **5090 JSON/JSONL documents**, including all historical
reserved/failed/actual seeds. Both original and derived artifact passed unchanged
loaders; the entire optimizer/model/RNG tensor payload stayed byte-identical.

The independently maintained backend's new protocol verifier was also exercised:
real `frozen_live_inference.py qualify` under Landlock/seccomp passed, including
exact parent lineage, all acquisition chronology checks and all original gates.
Fresh confined `replay` passed for actual newly collected path0 and path1 histories.
Logs, registry and environment:
`/tmp/opencode/nanfo-adr024-installation-check-3y1h6uhj/`.
This temporary registry has disposable offline-check UUIDs and a two-hour expiry;
it is **not** an installation into an existing network. Replay histories retain their
actual acquisition values and are not published as fresh snapshots. The verification
receipt pins the executed verifier revision; a subsequent unused-import lint cleanup
does not change the retained receipt or its results.

Final scoped tests: **6 passed**, including actual tensor rebinding and raw-report
tampering rejection. Campaign/verifier Ruff and whitespace checks passed. Earlier
recovery tests remain7passed. No additional measurements were taken during checks.

### Safe live feed startup for parent

1. Provision `live-registry.template.json` with actual network/workspace scope and
   current bounded expiry outside both producer roots. Set `NANFO_MODEL_ROOT` to
   the campaign root, `NANFO_MODEL_PYTHON` to the existing pinned AI interpreter,
   and the existing registry/hash/observation-root settings. First run confined
   qualification to reconstruct the new campaign; do not reuse ADR014 receipts.
2. Preregister a **different unused operational seed set**, adding3003..3014 to all
   historical reservations. Do not rerun this heldout campaign. Start a separately
   owned matching-image lab with truthful image ID and matching Linux/FRR actions.
3. The evaluation producer must create/fsync its session header, then wait **before
   reset**. Its feed must be protected and writable only by that producer. Obtain
   actual host-visible server PID/start ticks, boot ID and time namespace; use the
   session-line SHA256 **excluding newline** for passive admission (the qualification
   attachment hash includes newline and is not the same contract).
4. Build/pin the existing `nanfo.passive-feed-admission/v1` with that actual process,
   registry hash and fresh feed path. Start the existing passive bridge at EOF:

   ```sh
   PYTHONPATH=backend:. /path/to/backend/python -m emulation.passive_observer \
     --admission /protected/admission.json --sha256 "$ADMISSION_SHA256" \
     --duration-seconds 300
   ```

5. Verify the bridge has attached and captured its clock anchor before releasing
   the producer's reset gate. Only newly acquired nonterminal frames may publish;
   then exercise actual confined inference and durable recommendation. The campaign
   runner's `feed-attachment.json` records preregistered raw-acquisition chronology;
   it is **not a claim that a live bridge was running during qualification**. Do not
   use `adr024_campaign.py session` as an unsynchronized live-feed launcher.
6. Close/stop producer and bridge, verify unavailable snapshot/staleness behavior
   and exact-owned lab cleanup. Qualification now admits the derived model/image;
   current observation freshness and durable recommendation acceptance still require
   this live integration. Safety calibration and autonomous activation remain false;
   physicalRF remains blocked by absent equipment/surveys.

## Amended fresh qualification preregistration (published before traffic)

The accepted ADR024 amendment authorizes a new image-bound deployment artifact
through the unchanged writer/loader. Original checkpoint remains untouched.
`scripts/adr024_campaign.py` produced derived checkpoint SHA256
`77dae44acab722a5a6a2e87d952a6cca65e1c4eea102a089830a8401b521d614`;
the **entire tensor payload is byte-identical**, SHA256
`3e7e38ab4297ffd4b32b9c32d64af4b45e5f5ed1b2a74f9926f23379b0b0f967`.
Only `lab_provenance.lab_image_id` changed in the manifest. External `lineage.json`
binds parent, derived artifact, sources and truthful rebuilt image.

Active campaign directory: `/tmp/opencode/nanfo-adr024-evaluation-002`.
Plan SHA256: `b9e084a2c69241d3d5d3e2f60ab3f9052ee77e713befc1f43403fd21de8e4a30`.
Protocol: `adr024-rebuilt-evaluation-v1`. Fresh seeds **3003..3014**; audit recursively
examined all JSON/JSONL seed fields in `ai-engine/artifacts` and `emulation/output`,
including failed campaigns and reserved plans. Exact file hashes and reservations
are in `seed-audit.json`. Fixed policy order (shuffle seed9242026):
**PPO, heuristic, constant1, OSPF, constant0**. Each gets the same12 seeds, alternating
path0/path1,2-second windows and4 decisions; no training or tuning.

Campaign cap1800seconds, cleanup reserve120seconds, per-session cap600seconds.
All48 decisions per policy must be reconstructed from raw evidence; deployed PPO
action/probabilities must match original frozen deterministic replay. Both directions
require a strict majority correct. Reward gain over **each** constant must be>.02
with paired12-seed95%CI lower>0. OSPF goodputCI lower>0 and RTT CI upper<0. Heuristic
results retained regardless of outcome. A complete unfavorable campaign is final;
invalid/incomplete attempts are preserved and diagnosed. Calibration and autonomous
activation remain false regardless of this scoped benchmark outcome.

Each owned lab uses immutable image954462…, network-none, private PID namespaces,
privileged Mininet,2CPU/768MiB/256PID caps and bounded tmpfs. **No host filesystem
mounts**. Raw `/output` is copied only from its stopped owned container. Cleanup
checks exact ID/name/image/campaign label, removes that ID and verifies absence.
No other privileged workstream may launch until this role returns the slot.

Preparation002 follows preparation001 (no traffic): two unused imports and budget
accounting after startup were corrected before freezing the active runner.001 is
preserved; it is not a failed measurement attempt. Five new regression tests passed,
including actual original-writer tensor-byte equality and strict threshold boundaries;
scoped Ruff passed. Independent reviewer may inspect the published plan immediately.

The earlier image-mismatch finding below remains true for the **original** artifact;
the amended derived artifact is unqualified pending these new measurements.

## Result and handoff

**Exact v4 source recovered; distinct source-matched evaluation image built.**
The historical image is absent locally. Qualified live inference remains blocked
because the unchanged frozen validator also binds the original image ID. No
training, active measurement campaign, lab namespace, or route mutation occurred.
Parent owns serialized acquisition and any subsequent protocol decision.

Owned implementation: `scripts/recover_qualified_runtime.py` and
`scripts/test_recover_qualified_runtime.py`. This is offline operator tooling,
with no API, event, model-weight, database or frozen-source changes.

Protected recovery directory (mode0700):
`/tmp/opencode/nanfo-adr024-runtime-xfwykjez/`.
`recovery.json` contains all source maps, artifact pins, identities and boundary
results. Command argv/status/stdout/stderr, image inspections, dependency inventories,
build recipe and original extracted source remain alongside it. Each new invocation
uses a unique directory and tag; outputs are exclusive-create. Original evidence,
current emulation source and existing image tags were preserved.

## Exact identities

| Item | Value |
|---|---|
| Environment | `nanfo-matched-stationary-routing`, version **4** |
| Schedule | `seeded-stationary-capacity-v3` |
| Spec SHA256 | `bb15142a19ed3ee87a6aec2c6f9109d789d9736a5e6afda826ad898ef5fe7200` |
| Lab source-map SHA256 | `08c312c64154c9aedcd3b22eeb3573783590e0eb7183bc999cb8ef39b958dbbd` |
| AI source-map SHA256 | `04f797f8be02329adf15b44686d938c8898c21eca3fdb0d090afd5fe19153463` |
| Contract SHA256 | `bbcbbadec55792fa3f01bef511c1e38b0e433e125f896cdc3e64f823325e0fe6` |
| Checkpoint SHA256 | `5b8818af655ec8efce5d3bc3def27db599f3e0df379a0ae263dcefb5f72a80a5` |
| Tensor payload SHA256 | `3e7e38ab4297ffd4b32b9c32d64af4b45e5f5ed1b2a74f9926f23379b0b0f967` |
| Historical image, absent | `sha256:6b4ed91c2e7be7e4fbbb536ad3a808eb0e98c9d5f8165a5008846586893016ff` |
| Rebuilt evaluation image | `sha256:954462c0f00d5bbaa72ea144f6064936b399c430e6ab94bffcf1c00d134ea0d7` |
| New owned tag | `nanfo-adr024-v4-evaluation:64c0645681704358b41516aa36f0b108` |
| Inherited dependency base | `sha256:aafbad31e766488bbfd0709a5b12798677505c8bae3cc7b957405b0b16ecee03` |

AI runtime: Python3.12.14, torch2.8.0+cpu, numpy2.2.6, gymnasium1.2.0,
package0.1.0. Original loader actually passed in `ai-engine/.venv/bin/python`.
Lab runtime: Python3.9.23, FRR7.5.1-1.1+deb11u2,
Mininet2.3.0-1, Open vSwitch2.15.0+ds1-2+deb11u5.

## Recovery evidence

- `emulation/output/adr015-prechange-v4-source.tar.gz` matches preservation SHA256
  `444663dc3a7223044a9e8830ba5dd24cd3e1b041c60dc278e4bba56eb7252384`.
  All13 hashed lab files match the selected checkpoint; all36 regular archived
  files, including support modules/tests/configuration, were recovered byte-for-byte.
- `ai-engine/artifacts/adr014-001/source/` matches all14 checkpoint Python source
  pins. Its `pyproject.toml` hash is
  `d1837cdc330af3b8c0adba4e44eaccb183e32b5347d9a4ad34e8c5fabbee28f4`;
  `uv.lock` hash is
  `e7d9252cdbf2e54a17925f750345db90725b6ded4aacf8b38c295c697dfe6325`.
- `git show` checked both preserved commits without checkout:
  `0408c41e48a42f7cc0254b12bb3bdac9ea9805ac` matches7/13 lab files;
  `f9c67dbc3236e1e7e9ed41d7f91b2cc69e5f08c3` matches5/13. Neither is a completev4
  snapshot; the authenticated prechange archive is the complete recovery source.
- All five historical summaries agree on the exactv4 spec and image provenance;
  their complete raw log byte hashes match. The plan/selection/report pins also
  match. These are historical checks, not fresh observations.
- Existing operator image really isv5: spec
  `1c6a73af82830a048c9c9fc3997c10fd8e7f387012cac9af3ae22a37d003fa25`, source
  `ea8572f3635940e02e1418c62a211c009f6ec8e40f6c984f05d1a00c8544a177`.
- Rebuild inherits that image's dependencies, removes its emulation tree **inside
  the new image layer**, and copies the exact archived tree. The original hashed
  Dockerfile stays at `/opt/nanfo/emulation/Dockerfile`; the separate
  `Dockerfile.recovery` records the actual rebuild recipe. No package installation,
  pull, network access, or original-tag reassignment was used.
- All26 pinned requirements and pip/setuptools/wheel versions were verified;
  Python and the three explicit Debian package pins agree with the archived recipe.
  Full installed Python/Debian inventories are identical before/after rebuilding.
  Historically unpinned transitive Debian packages are recorded as inherited, not
  claimed identical to the unavailable historical image.
- The rebuilt image's actual `environmentSpec('matched')` equals the full manifest
  spec and hash. Build `pip check` passed; archived tests: **76 passed,2 live tests
  skipped**. Both static probe containers used network-none, read-only rootfs,
  dropped capabilities and no-new-privileges, and were removed by exact owned ID.
  Build intermediate containers were removed. The new evaluation image is retained.

## Unchanged validator boundary (actually executed)

`validator-boundaries.stdout` records original frozen CLI results:

| Diagnostic input | Outcome |
|---|---|
| Untouched historical measured history | Pass; action0, probabilities `[0.9718289375305176,0.028171034529805183]`, value3.2172513008117676 |
| In-memory copy changing only image ID to rebuilt ID | Reject: `inference image/source provenance differs from checkpoint` |
| In-memory copy with wrong source hash | Reject: `lab provenance differs from spec` |
| In-memory copy with wrong spec | Reject: `lab spec hash mismatch` |

The original measurement parser accepts a well-formed distinct image identity;
the subsequent original inference provenance equality rejects it. The `evaluate`
path checks full source/spec but does not enforce that same image equality. Therefore
an evaluation run may collect valid source-matched data while the unchanged live
inference/bridge remains unable to qualify it. `--generalization` does not waive
this image check. Setting `NANFO_LAB_IMAGE_ID` to the old ID would falsify provenance.
These altered copies were temporary unit diagnostics, never published as measurements.

## Parent-only evaluation command

The following command is prepared, **not executed**. Before use parent must save
its bounded ADR024 operational preregistration with fresh seeds disjoint from all
historical reservations, own the disposable isolated lab, and attach the feed bridge
before measurements. Selected-model inference on rebuilt-image records is expected
to hit the boundary above; collection cannot by itself close that gate.

Use an owned container name matching frozen transport's exact allowlist:
`nanfo-training-<32-lowercase-hex>` (the name does not make this a training command).
The container must use the rebuilt immutable image and report its **actual** image
ID in `NANFO_LAB_IMAGE_ID`. Do not invoke an old campaign supervisor or test-only plan:
those pin historical seeds and image identities.

From repository root, with `CONTAINER`, `OPERATIONAL_SEED` and a fresh `EVAL_OUTPUT`
set by the parent's saved preregistration:

```sh
PYTHONPATH=/tmp/opencode/nanfo-adr024-runtime-xfwykjez \
  ai-engine/.venv/bin/python -B -m nanfo_routing evaluate \
  --operator-experiment --container "$CONTAINER" \
  --split train --seed "$OPERATIONAL_SEED" --episodes 2 \
  --scenarios path0,path1 --mode matched --window 2 --steps 4 \
  --policy ppo --checkpoint "$PWD/ai-engine/artifacts/adr014-001/train-06/checkpoint.ptz" \
  --budget-seconds 120 --timeout 90 --output "$EVAL_OUTPUT"
```

`--split train` labels these fresh operational measurements as
`calibration-not-held-out`; it **does not train** with `evaluate`. Seed must be in
the original1000..1999 split, both consecutive seeds preregistered and unused.
The ordinary CLI immediately starts after its session header: parent needs a
separate acquisition synchronization wrapper to guarantee bridge attachment before
reset, as already described in `emulation/PASSIVE-OBSERVER.md`. No such campaign
or synchronization work was started by this recovery role.

## Registry configuration

`/tmp/opencode/nanfo-adr024-runtime-xfwykjez/registry.template.json` contains actual
checkpoint/source/contract/spec/runtime pins and byte references for the original
plan, selection, report and five raw benchmark sessions in preregistered order.
It intentionally requires actual network/workspace UUIDs and aware installation/
expiry times; it is not an installed registry or a live snapshot.

Parent creates a protected registry outside artifact and observation roots, fills
those fields, and computes its exact final byte digest. Existing settings:

```text
NANFO_MODEL_ROOT=/home/DHB/Documents/NANFO/ai-engine
NANFO_MODEL_PYTHON=/home/DHB/Documents/NANFO/ai-engine/.venv/bin/python
NANFO_LIVE_MODEL_REGISTRY=<protected absolute registry path>
NANFO_LIVE_MODEL_REGISTRY_SHA256=<SHA256 of final registry bytes>
NANFO_LIVE_OBSERVATION_ROOT=<separate protected observation directory>
```

Action bindings remain `route0`/`route1`, `linux-frr-host-route`, and
`nanfo.passive-measured-v4.v1`. No field in this registry authorizes image remapping.
The original benchmark can qualify its historical scope; rebuilt-image live
inference stays blocked with authentic image provenance. Calibration/activation
remain false. PhysicalRF remains externally blocked by absent survey/equipment.

## Reproduction

```sh
python scripts/recover_qualified_runtime.py audit
python scripts/recover_qualified_runtime.py prepare
python scripts/recover_qualified_runtime.py build
python -B -m unittest discover -s scripts -p test_recover_qualified_runtime.py -v
ai-engine/.venv/bin/ruff check scripts/recover_qualified_runtime.py scripts/test_recover_qualified_runtime.py
```

`audit` is read-only. `prepare` stages exact protected source and inspects Git/Docker.
`build` creates a unique new image and runs static tests plus historical boundary
diagnostics. None starts the emulation runner or acquires fresh measurements.

Recovery regression suite: **7 passed**; scoped Ruff passed. Tests cover archive traversal/link/device/duplicate/size
rejection, exclusive outputs, exact artifact recovery, dependency rejection,
uninstalled registry template and real frozen-validator boundaries. The first
test invocation exposed a Python3.14 test-fixture construction error: `TarFile.addfile`
requires a file object for a nonempty member. Supplying the bounded fixture payload
corrected that test; runtime recovery/build had already completed successfully.

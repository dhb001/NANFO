# ADR024 durable qualification evidence

Preserved on 2026-09-20 with the offline operator script
[`scripts/preserve_qualification_evidence.py`](../../../scripts/preserve_qualification_evidence.py).
The selected historical files are exact-byte copies, not edited exports. No new
measurements, lab launch, training, firmware changes or model installation occurred.

## Locations and sizes

| Location | Contents | Size |
|---|---|---:|
| [`QualificationEvidence-ADR024/`](QualificationEvidence-ADR024/) | Selected results, plans, lineage, independent reviews, source hashes, checksums and complete raw-file relocation inventory | 833,423 bytes including directory entries; 896 KiB allocated |
| `ai-engine/artifacts/adr024-qualified-001/` | Reusable model, parent checkpoint, frozen source, benchmark sessions, underlying measurements, live sessions, native transcripts and supporting source | 158,332,355 bytes including directory entries; 155 MiB allocated |

The local artifact set contains **1,107 selected source files / 157,709,961 payload
bytes** (150.4 MiB), plus manifests and the completion receipt. The compact document
payload is 829,489 bytes before its checksum file and completion marker. Full raw
logs, models and the large benchmark/seed-audit reports are only in the artifact
root, which is covered by the existing `ai-engine/.gitignore` `artifacts/` rule.
The compact directory is Git-eligible. Nothing was staged or committed.

All generated evidence directories are mode `0700`; files are mode `0600`.
Publication uses the existing release tool's descriptor-relative, no-follow,
no-clobber, fsynced file writer and exact readback. Original inputs are never
modified. A byte cap and explicit filename/source-pin allowlists bound selection.
The deployment archive schema only admits deployment-verifier results/resource
ledgers; this campaign therefore uses its own versioned manifests rather than
claiming compatibility with that archive schema.

## Historical campaigns and scoped results

| Campaign | Original root | Preserved local root | Review/result |
|---|---|---|---|
| Rebuilt model benchmark | `/tmp/opencode/nanfo-adr024-evaluation-002` | `model/` | [Outcome](QualificationEvidence-ADR024/evaluation/outcome.json), [independent reconstruction](QualificationEvidence-ADR024/evaluation/independent-verification.json), [separate runtime review](QualificationEvidence-ADR024/review/adr024-independent-runtime-review-final-002.json) |
| Continuous service acceptance | `/tmp/opencode/nanfo-live-acceptance-7ngrbdgv` | `live/` | [Result](QualificationEvidence-ADR024/live/result.json), [final independent review](QualificationEvidence-ADR024/review/adr024-final-live-independent.json) |
| Manual native driver | `/tmp/opencode/native-driver-02z3yisx` | `native/` | [Result](QualificationEvidence-ADR024/native/result.json), [final independent review](QualificationEvidence-ADR024/review/adr024-final-native-independent.json), [prefix/readback reconstruction](QualificationEvidence-ADR024/review/adr024-final-native-readback.json) |

The benchmark passed its preregistered scoped gates. The live independent review
records six frames, four recommendations and twelve durable exported rows, with
exact original frozen inference. Native evidence records 38 raw command cases,
480 mutations, 460 snapshots and 54,646 native commands, plus four owner exception
cases. The native fixture is a static-FIB Mininet graph; FRR/OSPF daemons were not
started. Preserve the independent reviews' limitations: owner receipts support
some cleanup/permission/exception outcomes; there is no new live DB query here.
Autonomous dispatch, safety calibration, hard transition deadline proof and
physical RF qualification remain unclaimed/false.

The final independent review JSON files were copied directly from
`/tmp/opencode/adr024-final-native-independent.json` and
`/tmp/opencode/adr024-final-live-independent.json`. Their original review scripts
are also retained under local `review/`; their historical absolute path constants
remain intact. They are not silently rewritten into portable verifier scripts.

## Immutable hashes

All values below are SHA-256 over exact file bytes, except the explicitly named
tensor payload, which is the unchanged `weights.pt` ZIP member.

| Item | SHA-256 |
|---|---|
| Original `model/parent-checkpoint.ptz` | `5b8818af655ec8efce5d3bc3def27db599f3e0df379a0ae263dcefb5f72a80a5` |
| Derived `model/checkpoint.ptz` | `77dae44acab722a5a6a2e87d952a6cca65e1c4eea102a089830a8401b521d614` |
| Shared complete tensor payload | `3e7e38ab4297ffd4b32b9c32d64af4b45e5f5ed1b2a74f9926f23379b0b0f967` |
| `model/test-report.json` | `e6ee9c1bd99e3f6961db497db664335684fa277bd1a1c86a8034570ac116056d` |
| `model/plan.json` | `b9e084a2c69241d3d5d3e2f60ab3f9052ee77e713befc1f43403fd21de8e4a30` |
| Final native independent review | `367f6512a18cbc9d2745e97b711557b4c75bccd2f7fc3e0e097e6df6747a25b8` |
| Final live independent review | `52068becc0787c851548382f533ec1a2be75df313ca41ce72bb80935c9aa9d69` |
| [`checksums.json`](QualificationEvidence-ADR024/checksums.json) | `1a858c59e25c35cb92bbe9d50a6c29ce21050ad276a327bd35938871f28901e7` |
| [`raw-manifest.json`](QualificationEvidence-ADR024/raw-manifest.json) | `381ed409385d7cc5e8e53006c14650627706d802a7f6769b88efe86cd3b993b9` |
| [`relocation-receipt.json`](QualificationEvidence-ADR024/relocation-receipt.json) | `389cc88ef71340bb6e5f60b977d86ab66ef506ab25dd2162f01277fd9037be0e` |
| [`source-hashes.json`](QualificationEvidence-ADR024/source-hashes.json) | `94c5c233e3916aa41a97c875d1851afed164c1e1df524c31288c221bcfe66b84` |

`relocation-receipt.json` maps each selected source root/path to its relative
destination, byte count, source digest and identical destination digest.
`raw-manifest.json` inventories every selected local file. `source-hashes.json`
indexes frozen AI, live-service, native, recovery and preservation-tool sources.
Large historical manifests stay unchanged even where they describe excluded files.
The new raw manifest alone defines what this preservation set actually contains.

## Portable registry roots

Let `B` be the absolute path to the relocated **whole** local artifact directory:

| Purpose | Path relative to `B` |
|---|---|
| Model artifact root (`NANFO_MODEL_ROOT` for a separately authorized installation) | `model` |
| Unfilled live registry template | `model/live-registry.template.json` |
| Historical deployment descriptor | `model/deployment-registry.json` |
| Historical live registry, separate from model/observation roots | `live/registry.json` |
| Historical observation root | `live/observations` |
| Frozen AI source | `model/source` |
| Exact historical AI dependency manifests | `model/dependencies` |

All **17 deployment references, 22 template references and 22 historical live
references** resolve and match after relocation, including parent checkpoint,
lineage, seed audit, plan, selection, report and all session attachments. All
fourteen frozen source hashes match. Historical scope `snapshot.json` resolves
under `live/observations`, not under the model root.

Registry bytes already contained relative references and were copied unchanged.
Absolute paths in historical plans, transcripts, source manifests and acquisition
metadata are preserved as provenance; use the relocation receipt to locate the
copies. Feed inodes, timestamps, expiry and admission hashes are not freshened.
The template still requires real installation scope/times; the retained historical
installation grants no current authority. Runtime binaries, image layers and
private stores are not part of this portable evidence set.

## Exclusions and privacy

The selected text/JSON/JSONL and embedded JSON transcripts passed credential
screening. The two binary model files are pinned to the original known hashes;
their member sets, manifests and full tensor hashes were also checked without
deserializing arbitrary binary inputs during preservation.

Excluded by allowlist: admission/expired-admission files and tokens; environment
files and environment-bearing Docker inspections; private credentials/signing
keys; generic stdout/stderr/build/producer/bridge/container/host logs; lock files,
release signals, manual native authority files, caches/dotfiles and native compose
configuration. No credential values are copied or printed by the preservation
script. Historical admission **hash references** remain where already recorded;
the admission documents themselves are not exported.

| Original capture root | Excluded files | Excluded bytes |
|---|---:|---:|
| Evaluation | 181 | 109,708 |
| Live | 19 | 3,164 |
| Native | 22 | 98,423 |

Those counts concern the three named capture roots only. No recursive copy of
`/tmp/opencode`, private stores, runtime environment or key directories was made.
The original captures remain in place. The full historical live/native auditors
require some deliberately excluded admission/container records, so their complete
original audits cannot be rerun from this credential-free subset unchanged. Their
final independent results are preserved, as are the selected raw measurements and
native command/readback evidence. This limitation is explicit in the receipt.

## Offline validation and operator commands

From the repository root:

```sh
# Read-only integrity, secret screening, tensor pins and registry closure.
python -B scripts/preserve_qualification_evidence.py verify

# Original frozen report reconstruction and recorded inference; no lab/services.
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  ai-engine/.venv/bin/python -B scripts/preserve_qualification_evidence.py replay

# Safety regression tests.
python -B -m unittest discover -s scripts -p test_preserve_qualification_evidence.py -v
```

Both verification commands also accept `--artifacts /absolute/new/root` and
`--documents /absolute/evidence/root`; they do not read the old `/tmp` sources.
`verify` uses only the standard library and the existing release helper. `replay`
requires the matching AI dependencies; its frozen loader reconstructs the entire
five-policy report from copied raw sessions and checks exact saved-report equality.
It then runs recorded-history inference: **path0 → action1**, **path1 → action0**.
Both operations passed on the relocated copies. Eleven safety tests and scoped Ruff
checks passed.

For another authorized preservation run, `inspect` screens and reports sizes
without writing; `preserve` requires two fresh, protected, non-temporary output
roots. It refuses existing destinations. The initial copy here reached the command
runner's 120-second timeout during final verification after all copies/manifests
were published. `finalize` was added to verify an interrupted complete copy and
publish only missing identical completion markers. It completed successfully with
a longer timeout; no payload or manifest was replaced. The pinned local
`preservation-source/scripts/preserve_qualification_evidence.py` records the
copy-time script, before that small finalization addition. The current operator
script contains the recovery operation.

[`preservation-complete.json`](QualificationEvidence-ADR024/preservation-complete.json)
records the successful copy verification and checksum-root digest. Keep the
Git-ignored artifact directory when moving this workspace; the compact manifests
describe it but cannot replace its raw bytes.

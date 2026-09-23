# ADR027 accepted review-closure evidence

Preserved on **2026-09-21** under [ADR027](../../adr/ADR-027-repository-review-closure.md).
**Latest core acceptance: [refresh-c8rorfzd](refresh-c8rorfzd/)** — 28 passed,
0 failed, 5 optional blocked. The deployment owner exported eight pinned evidence
files plus selection/manifest/checksums: **11 files / 243,293 bytes**.
The earlier [accepted bundle](accepted/) remains intact: **31 evidence files**,
plus selection/manifest/checksums: **34 files / 336,608 bytes**. Its browser and
dependency receipts retain their original bounded scopes. Verification needs only
these directories and repository tooling; original `/tmp` paths are provenance.

## Latest core refresh and durable retention

[Refreshed source comparison](refresh-c8rorfzd/deployment/source-comparison.json)
records the accepted runtime aggregate
`f7105617ee9cad1ae51e2f223761885c9223ee22d4d586a08ff36a5f87e89d05`
and API image
`sha256:a2bf67af00b76980beec822f9c7f1fcb0e6d4ef2e1e6461b169b9b3ff3397b39`.
At deployment-owner final comparison all725 runtime paths matched, with no additions
or removals. Of1,129 frozen paths, only `ai-engine/README.md` differed; it is not
installed in the core image. This refresh includes the dependency/race/tooling
changes described in the historical comparison below. It does not repeat the
browser lane or qualify experimental/model/physical capabilities.

New ignored local destinations under `ai-engine/artifacts/`:

- `adr027-review-backup-c8rorfzd/`: **14 exact original files / 593,952,186 bytes**
  (11 encrypted volumes, one encrypted binding, manifest and HMAC), plus receipt.
- `adr027-review-key-c8rorfzd/`: separate 32-byte key copy.
- `adr027-review-originals-c8rorfzd/`: exact original verifier result.

[Retention evidence](retention-c8rorfzd/) contains two public records plus its
selection/manifest/checksums. [Readback verification](retention-c8rorfzd/backup-verification.json)
confirms original/durable archive bytes and separately stored keys match for **both**
`c8rorfzd` and `dr_i6gb8`. Exclusive creation and an actual repeated-copy refusal
verified no clobber. The new archive passed the existing backup verifier's manifest
HMAC, ciphertext, GCM authentication and TAR validation for11 volumes plus1binding.
Both prior and new original temporary archives/keys remain intact; private files
are0600 and new directories0700. This remains **local retention, not off-host escrow**;
external secret mounts are not included.

| Latest preservation identity | SHA-256 |
| --- | --- |
| Refresh export manifest | `e4235f4eaadd09a0aa9f146c96cc36fc2d3dea832f05a388c3a5ab18b1677fa4` |
| Refresh SHA256SUMS | `e48d632d8268fcbb699c0863fe484d4307ae0a4db849f42dd4b0531174cead2e` |
| New backup manifest | `6363dd09efaa29957c237182f0018412e7d2dec43ea21acfa884e5c789bed9a3` |
| Original new verifier result, private | `aea363391faff9d85de241c7459ccc0dd79eb82b1bc5bec3bbc9cb7ad8cb742c` |
| Retention export manifest | `5e76ed72001edc5025423606c146c9ee63d176b446b1b528f8d153ceebbda757` |
| Retention SHA256SUMS | `6ab7f768f76aa4510201680005fc49f8e831b7419c1ff0e65571b26fd01bcf27` |

## Experimental017 / independent018 reference supplement

[experimental017-018](experimental017-018/) contains **six evidence files** plus
selection/manifest/checksums: exact017 result, postrun audit, cleanup, cleanup
verification, exact independent018 review, and a new reference-only summary.
[Diagnostic reference](experimental017-018/reference-summary.json) retains the
original diagnostic's location, byte count and SHA-256; its68-case body remains in
the original private inventory. No seed arrays, policies, admissions, tokens or
raw frames were copied. The existing `seed_values()` extractor returned an empty
set for every selected record: **zero operational values published**.

017 remains **failed:67/68 matrix cases complete, one invalid measurement**, with
four separate smokes complete and cleanup recorded. Recovery does not validate
the failed measurement. The [independent018 review](experimental017-018/018-independent-review.json)
supports the bounded protected-read repair but grants no launch: correcting one
count-only scanner false positive leaves996 genuine/preregistered reservations,
four available versus36 required. No new plan or campaign acceptance follows.

Supplement manifest SHA-256:
`97b6b5106201f9e8f23c52e6fcc6532ad825d080563eb4af78473b6932d8f61f`.
SHA256SUMS SHA-256:
`d1c9aa18ad54fa4ec2565009ce49100c26fb296179a464154588f5c291a60e71`.

## Earlier accepted scopes and links

| Evidence | Preserved result | Owner handoff |
| --- | --- | --- |
| [Deployment status](accepted/deployment/result-status.json) | `dr_i6gb8`: 28 passed, 0 failed, 5 blocked; core true; Step15/all-green false | [Deployment](../ReviewClosure-Deployment.md) |
| [Full-stack receipt](accepted/fullstack/r09-live-08.json) | Production browser 5/5, zero failures/errors/skips; cleanup true; stable during-run source digest | [Fullstack](../ReviewClosure-Fullstack.md) |
| [Dependency readback](accepted/dependencies/audit-readback.json) | All four retained Python reports match their inventories and reviewed summaries | [Dependencies](../ReviewClosure-Dependencies.md) |
| [Backup manifest](accepted/deployment/backup-manifest.json) and [authentication](accepted/deployment/backup-authentication.json) | Eleven encrypted volumes and one binding; copied archive authenticated again | [Evidence hygiene](../ReviewClosure-Evidence.md) |

### Exact bytes and hashes

[selection.json](accepted/selection.json) records each original path, byte length
and SHA-256. [manifest.json](accepted/manifest.json) pins the exported files;
[SHA256SUMS](accepted/SHA256SUMS) also covers the manifest. Original receipts,
freeze/runtime manifests, image records, backup manifest, dependency inventories,
raw **advisory-feed JSON** and summaries were exported without byte rewriting.
Generated preservation/readback records are explicitly new observations.

The deployment original contains `generated_password: true`, a boolean generation
indicator conservatively refused by the existing scanner. Its exact 17,643 bytes
are privately retained, and the existing
`deploy/release_manifest.py:project_result` produces the published status-only
projection. [Projection provenance](accepted/deployment/result-projection.json)
pins both original and projected bytes. No scan exemption or silent rewriting was
used. Original diagnostic detail is not part of the public result projection.

| Identity | SHA-256 |
| --- | --- |
| Export manifest | `828d17a29ad95aded7326293ee3ddffcdb037163f2113ad6e8160ec5c6ec517c` |
| SHA256SUMS file | `8f230eb0120d5386a292d1c7dc9aafbcee8995680a13235ea32f76bc7a6b42d3` |
| Original deployment result, private | `df4ea858a9a7669cd7f0cce8ae211a041c8f782cb47f6f36fb2ed08b8c67d357` |
| Original full-stack result, public | `bd87ef5a83f44b0da975f4bef4931c4a9a2f25ee906da5a0b0a24ef64ce6322b` |
| Original full freeze manifest | `4931ad08f920dc3a309c9cdec0f26d69c8d2b2a5062fbb6fc6ab44759caddff1` |
| Original runtime manifest | `1674c218d0b5dd0077308cc66f003c5577c0732e9ea9074428ef72799a990bd0` |
| Original backup manifest | `387b4a533d6b48d7609e9293d2f10eb42ea32e5862d98edcbcb1cc7b6d371c90` |

### Historical first-preservation comparison — superseded by core refresh above

[Source comparison](accepted/deployment/source-comparison.json) is a point-in-time
observation at approximately **16:28 UTC**, not a new deployment acceptance.
All 1,127 original freeze files still matched the original frozen tree. Against
the working tree, **1,118 matched / 9 changed / 0 missing**; the narrower 724-path
runtime manifest had **719 matched / 5 changed / 0 missing**. Additional working-tree
files are explicitly outside those listed-path comparisons.

- Documentation: `ai-engine/README.md`.
- Tests: `backend/tests/integration/test_gateway_headers.py`,
  `backend/tests/unit/test_experimental_campaign.py`,
  `emulation/tests/test_experimental_lab.py`.
- Dependency inputs: `backend/pyproject.toml`, `backend/poetry.lock`. Parsed main
  dependency declarations and every main-group lock record match the freeze;
  fakeredis development extras changed and development-only lupa2.8 was added.
  The complete files nevertheless have different hashes.
- Runtime/tooling copied by the backend Dockerfile:
  `backend/scripts/verify_experimental_lab.py`,
  `emulation/experimental_lab_contract.py`,
  `emulation/experimental_lab_receiver.py`. These are genuine installed-source
  differences, not documentation-only drift. The original receipt remains tied to
  its earlier frozen image; the separate core refresh above covers the later build.

[Installed dependency probe](accepted/deployment/installed-dependencies.json)
rechecked the exact accepted API image read-only, network-none: FastAPI0.135.4,
Starlette1.6.0, Pydantic2.13.4, cryptography50.0.0, Uvicorn0.32.1.
The [source image record](accepted/deployment/e89f4ea622cf4caa8be968498b297c60-images.json)
and [restore image record](accepted/deployment/61ba32fae94b41669b658678e9fc76ac-images.json)
retain exact image IDs. No replacement application image was built here.

The [full-stack digest comparison](accepted/fullstack/source-comparison.json)
also differs from both the deployment freeze and the later working tree. Its
receipt proves stability during its own run only; the distinct aggregates are
not equated. Build-output hashes remain in the original browser receipt.

### Dependencies: bounded historical audit

Preserved backend results are the **post-Lua** audit; AI, supplemental upstream
Torch and emulation results are the strict-schema review audits. Offline readback
revalidated inventories, summaries and the [exact exception policy](accepted/dependencies/exception-policy.json)
as of 2026-09-21. This was not a fresh advisory-feed query.

- Backend: two raw rows / one distinct reviewed ecdsa pair.
- AI CPU lock: zero reported rows, **Torch2.8.0+cpu coverage gap**.
- Supplemental upstream Torch: eight reviewed pairs; not CPU-wheel certification.
- Emulation: 48 raw rows / 26 reviewed pairs; aliases are not independent CVEs.
- Exceptions expire **2026-10-21**. Policy acceptance does not fix vulnerabilities.
- [Retention XML](accepted/dependencies/retention.xml): 27 actual passes;
  [proxy XML](accepted/dependencies/proxy.xml): one actual pass.
- [PostgreSQL receipt](accepted/dependencies/lua-postgres.json): 254 passed and
  12 skipped, still `partial`. The separately reported Redis12 result has no
  retained standalone receipt here. npm0 is handoff-reported; its raw receipt was
  unavailable and was not reconstructed. Remote CI is not established here.

## Earlier private durable retention — retained intact

New ignored directories under the existing local `ai-engine/artifacts/` store:

- `adr027-review-backup-dr_i6gb8/`: **14 exact original files / 593,952,186 bytes**
  (12 encrypted archives, manifest and HMAC), plus a preservation receipt.
- `adr027-review-key-dr_i6gb8/`: separate 32-byte key copy.
- `adr027-review-originals-dr_i6gb8/`: original deployment result only.

[Backup preservation receipt](accepted/deployment/backup-preservation.json)
records all ciphertext hashes and locations, without key values. New directories
are0700/files0600; exclusive creation, byte readback, manifest HMAC and ciphertext
checks passed. Existing backup tooling additionally authenticated all GCM archives
and validated their TAR content. Original temporary archives and key remain intact.
This is local durable retention, **not off-host escrow**. External source/restore
secret mounts and private diagnostics were not copied; the public evidence bundle
is not a self-contained disaster-recovery kit. No raw archive or key belongs here.

## Verification

From the repository root (public verification requires no private store):

```sh
python scripts/preserve_review_closure.py verify --destination docs/project/ReviewClosureEvidence/accepted
python scripts/preserve_review_closure.py verify --destination docs/project/ReviewClosureEvidence/refresh-c8rorfzd
python scripts/preserve_review_closure.py verify --destination docs/project/ReviewClosureEvidence/retention-c8rorfzd
python scripts/preserve_review_closure.py verify --destination docs/project/ReviewClosureEvidence/experimental017-018
python scripts/evidence_hygiene.py scan --root docs/project/ReviewClosureEvidence
python -m unittest discover -s scripts -p test_preserve_review_closure.py -v
```

Locally, append `--known-private ai-engine/artifacts/adr027-evidence-private-20260921-001`
to verification/scanning to also match all71 previously contained receiver values.
No fixture policy is accepted by export or used for this directory's scan.
`preserve_review_closure.py export --plan FILE --destination NEW_DIRECTORY` reuses
the existing allowlisted exporter and refuses existing output or changed pins.
`compare --source accepted-manifest.json` reports listed-path drift explicitly.

Eight preservation regressions and scoped Ruff passed. Portable bundle verification
and directory scanning passed with zero findings and zero fixture exemptions.
These records support the bounded core/browser/security-policy scopes above;
they do not qualify physical/lab/model/distributed Step15 capabilities, measured
telemetry survival, scientific studies or the whole platform. Master closure/status
documents remain coordinator-owned. No commits were made.

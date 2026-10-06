# Tracked copies of the qualified ADR024 runtime (ADR-028)

`adr024-qualified-001/` holds byte-identical copies of ignored private evidence, so the
qualified model identity can be verified from a clean checkout. Nothing here is a new
training run, a re-qualification or a relabelled result.

| Tracked copy | Private original | Pin |
|---|---|---|
| `model/checkpoint.ptz` | `artifacts/adr024-qualified-001/model/checkpoint.ptz` | `MODEL` in `emulation/experimental_lab_contract.py` |
| `model/parent-checkpoint.ptz` | same directory (== `artifacts/adr014-001/train-06/checkpoint.ptz`) | `PARENT_HASH` in `scripts/refinement/frozen.py` |
| `model/lineage.json`, `model/recorded-history-path{0,1}.json` | same directory | `SHA256SUMS` |
| `live/path0/snapshot-0.json` | `artifacts/adr024-qualified-001/live/path0/snapshot-0.json` | `SHA256SUMS` |
| `client-source/` | `artifacts/adr014-001/source/` (14 modules + historical `pyproject.toml`/`uv.lock`) | `client_source_sha256` in `model/lineage.json` |

`client-source/` is the frozen ADR014 client that the checkpoint manifest binds to
(`client_source_files`). It equals `src/nanfo_routing` at commit `e55a4f5`; later edits to
`src/nanfo_routing` form a successor client that cannot load this checkpoint, so historical
checkpoints are loaded only through this copy (or the private original). The frozen v4 lab
source archive is tracked separately in `emulation/frozen/`.

`tests/test_frozen_identities.py` verifies `SHA256SUMS`, the pinned `MODEL`/`IMAGE`/`SOURCE`
identities, the lineage, re-derives `SOURCE` from the archive and loads the checkpoint with
the frozen client (`torch.load(..., weights_only=True)`). Ruff excludes this directory.

# Schema0027 integrated acceptance evidence

## Latest postreview refresh

Both unchanged lanes passed on current reviewed production sources: inventory15/15,
measured/retention10/10, exit0, runtime/installed0027, no blockers or source drift.
The original stable and partial results below remain unchanged.

| Exact file | SHA-256 |
|---|---|
| `inventory-result-postreview.json` | `d2a26ee24605cf7e5abecfcb85887ceab121ce4fd722a173d8b94302e15da1ab` |
| `measured-result-postreview.json` | `5f2ea62d9734b62e9cda9c6edff28abd5f1a5ef44bd04a6b70817f77b1461e5e` |

`checksums-postreview.json` records exact byte lengths56729/59252 and the empty
source-drift lists. Original directories under`/tmp/opencode/`:
`measured-twin-acceptance-_db04_73` and`measured-twin-acceptance-oagzuikf`.
Scoped regression382 passed; exact cleanup independently checked. No scope or
verifier-source change, source-gate narrowing or measured-value substitution.

## Previous accepted run

Final outcomes: **inventory15/15 passed; measured/retention10/10 passed**, exit0,
runtime/installed0027, stable source hashes within each final run, no blockers.

| Exact file | SHA-256 |
|---|---|
| `inventory-result.json` | `b3961157e57a8d28aad7118c3bc9d4448c46422c4dfcea5b1ec15cf552652011` |
| `measured-result.json` | `5932961885a980b380170e4b33bad52a672cb945d8e3b9ab57acbb77d96250eb` |

`checksums.json` contains hashes/byte lengths/status and changed-source lists for
all eight exports. The six `*-source-drift-*.json` results passed all functional
cases but retained partial status because their before/after source hashes changed.
Final originals are `/tmp/opencode/measured-twin-acceptance-g97dkfg6/result.json`
and `/tmp/opencode/measured-twin-acceptance-k94ncz7_/result.json`.

Credential-free exact verifier results and SHA-256/byte-length catalog. Earlier
schema0024 evidence remains in its original directory. See
[IntegratedAcceptance.md](../IntegratedAcceptance.md) for final statuses and limits.

Cases include the original14 inventory and8 measured checks plus generated
geometry roundtrip/history/denials, report pin-before-reference using real SNMP
records, and actual archive/delete/tombstone replay/restore. Geometry is explicit
acceptance metadata; SNMP measurements are actual loopback counters.

Partial attempts with every functional case passed remain retained when concurrent
source edits failed the verifier's whole-source stability gate. Source manifests
identify these changes; those attempts are not silently relabeled as passed.
No credentials, JWTs, service configuration, logs or database dumps are exported.

Graph projection remains substituted/unverified, websocket transport is collecting
rather than a live network socket, and full Compose/physical acceptance is outside
this campaign.

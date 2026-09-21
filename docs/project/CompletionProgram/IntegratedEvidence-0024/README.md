# Final schema0024 integrated local acceptance

Exact credential-free verifier result bytes, including source manifests, measured
counter summaries and cleanup evidence. Both lanes exited0 with status`passed`,
runtime/installed schema0024, no blockers and stable source hashes.

| File | Cases | SHA-256 |
|---|---:|---|
| `inventory-post-asset-fixes-result.json` (latest inventory) |14 passed| `5ca8c9d5721450fb70289bb71ea5028c66e665b141f0b673cfd0b49129476632` |
| `inventory-result.json` |14 passed| `5c922ae9616d0678c840f442fb4fa7a2e1131d34a779671a174777755fb9a78e` |
| `measured-result.json` |8 passed| `ed035d60a51b67852e270d70e43210dbe7140413ab9d145c5c341d64b5ff3244` |

Original run directories under `/tmp/opencode/`:
`measured-twin-acceptance-19tb4_x0` (inventory),
`measured-twin-acceptance-_tasizi5` (measured).
Private resource trees were deleted before result serialization. Only results,
not logs, credentials, database dumps or runtime configuration, were exported.
`checksums.json` independently records exact byte lengths and hashes.

The inventory lane was refreshed after asset crash-orphan hardlink recovery and
the final-response-read authority recheck fixes. Latest original directory:
`/tmp/opencode/measured-twin-acceptance-sxow0og6`. Its exact46347-byte result and
digest are recorded separately in`post-asset-fixes-checksums.json`. Earlier files
and checksums remain unchanged. The measured lane was not rerun for this refresh.

These are local-service results, not full Compose/physical acceptance. Topology
projection remains substituted/unverified; websocket evidence uses the actual
manager/auth with a collecting transport substitute, not network sockets.
See [IntegratedAcceptance.md](../IntegratedAcceptance.md) for the full handoff.

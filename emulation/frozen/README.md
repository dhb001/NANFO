# Frozen v4 lab source (ADR-028)

`adr015-prechange-v4-source.tar.gz` is a byte-identical tracked copy of the ignored
`emulation/output/adr015-prechange-v4-source.tar.gz` (SHA-256 in `SHA256SUMS`, also pinned as
`ARCHIVE_HASH` in `scripts/recover_qualified_runtime.py`). Its 13 `source_files` re-derive the
pinned lab `SOURCE` digest (`emulation/experimental_lab_contract.py`) as
`sha256(canonical_json({name: sha256(emulation/<name>)}))`; see
`ai-engine/tests/test_frozen_identities.py`. It is historical evidence: never edit it, and
never treat the running lab as this source. The successor lab requires fresh qualification.

<!-- Title: Type(area): imperative summary [FINDING-ID]  (see CONTRIBUTING.md) -->

## Finding

<!-- One finding per pull request: ADR contract, review finding or issue, e.g. ADR-028 C22. -->

## What changed and why

## Tests

<!-- Exact commands and pass/fail/skip counts (CONTRIBUTING.md "Test commands"). -->

```text
```

## Checklist

- [ ] One finding only; no unrelated refactors or formatting.
- [ ] Regression test added or updated; no assertion weakened, no new skip or `--deselect`.
- [ ] API changes keep the `{success, data, meta, errors}` envelope and are additive, or the ADR marks them BREAKING (described above).
- [ ] New `Settings` fields are documented in `backend/.env.example`; new DSN-gated suites are listed in `disposable-integration.yml`; new private-evidence tests are listed in `backend/tests/private_artifacts.txt`.
- [ ] No secrets, `.env` files, `deploy/state/`, `ai-engine/artifacts/` or other private evidence (`scripts/evidence_hygiene.py scan --tracked --include-untracked` passes).
- [ ] Frozen runtimes and historical evidence are untouched, or the successor/requalification plan is linked.
- [ ] Docs, ADR status and `docs/project` notes updated where behaviour changed.

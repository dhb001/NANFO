# ADR027 / R01 — Evidence-hygiene handoff

## Delivered and verified (21 September 2026)

This is the R01 owner handoff within ADR027's seven-workstream closure. Owner files:
`scripts/evidence_hygiene.py`, `scripts/test_evidence_hygiene.py`, `.gitignore`, this
document and the 71 campaign credential deletions. The subsequent explicit CI scope
adds `.github/workflows/evidence-hygiene.yml`, `security/evidence-fixtures.v1.json`
and removal of the unused active `backend/alembic/alembic.ini` sample URL.

## CI gate follow-up — delivered

The dedicated **Evidence hygiene / Credential and evidence gate** workflow runs on
pull requests, main/master pushes and manual dispatch. Actions are commit-pinned,
checkout credentials are not persisted, permissions are read-only, Python is
3.12.14 and the job timeout is 30 minutes. The standard-library-only scanner tests
run before the entire tracked-tree scan; any test failure, scanner finding, invalid
policy or uninspectable/budget-exhausted content fails the job. There is no
`continue-on-error`, path-filtered scan, package installation or private-artifact
dependency. Existing shared workflows and dependency policy were not edited here.

### Full current-tree verification

Executed from the repository root:

```sh
python scripts/evidence_hygiene.py scan --root . --tracked --include-untracked --fixtures security/evidence-fixtures.v1.json --known-private ai-engine/artifacts/adr027-evidence-private-20260921-001
ai-engine/.venv/bin/python -m unittest discover -s scripts -p test_evidence_hygiene.py -v
```

- **PASS: 8,400 selected files**, comprising 8,421 index entries minus 71 pending
  credential deletions plus all 50 nonignored new files at execution time.
- **9,061 inspected entries / 1,447,057,301 bytes**, counting nested archive members
  and their decompressed bytes; **zero findings** after reviewed policy.
- **53 exact file-hash matches / 57 specific rule exceptions**. Policy hashes were
  independently checked against current bytes: zero stale paths.
- All five new root scripts were included: `audit_dependencies.py`,
  `evidence_hygiene.py`, `run_portable_tests.py`, `test_audit_dependencies.py`, and
  `test_evidence_hygiene.py`. No special exclusion for new scripts or tests.
- **20 tests passed on Python 3.12.14**, matching the workflow, and on local
  Python 3.14. Tests include a disposable Git index, inclusion of new extensionless
  credentials, rejection after modifying an excepted fixture, and unconditional
  refusal of receiver credential-file exceptions. No database/services are needed.
- Ruff passed; workflow YAML parsed with read-only permissions and all four steps;
  Alembic `poetry run alembic -c alembic/alembic.ini heads` returned `0029 (head)`.

This is executed local gate validation. Remote GitHub execution and configuring the
check as branch-protection-required remain coordinator/repository-administrator
actions; no remote CI pass is claimed.

### Reviewed exception authority and exact omissions

`security/evidence-fixtures.v1.json` is the sole CI exception policy. Each entry
names the exact path, entire file SHA-256, specific rules and a review reason.
No directory, glob, archive-container or unconditional test exemption exists.
Changed bytes lose the exception. Known receiver values and credential filenames
cannot be excepted. Export still accepts **no** fixture policy.

The 53 reviewed files are:

- **29 synthetic test/probe files**: negative auth/DSN/key-marker tests, non-login
  password markers, pytest-only signing config, fake SNMP actors and frozen
  unavailable-host import probes. No key payload or issued receiver token is exempted.
- **14 historical JSON result records**: the only sensitive-key finding is
  `generated_password: true`, a boolean generation indicator, not a password.
- **Seven non-secret source references**: runtime auth-store/session lookups and
  environment-to-secret-mount filename maps; exact hashes pin the reviewed sources.
- **Two frozen public sample configurations**: historical Alembic template URL and
  historical Compose development defaults. These are authorized only as immutable
  provenance, never as active deployment settings.
- **One disposable CI service configuration** with public deterministic job-local
  PostgreSQL credentials. The precise authoritative list is the policy itself.

All selected files are still read and inspected; exceptions suppress only named
findings on matching bytes. Selection omissions are exactly: Git history/object
database, the 71 pending deleted credentials, and Git-ignored untracked files
(including private `ai-engine/artifacts`, local `.env`, caches and dependencies).
The CI command uses `--tracked`; new source is naturally included after commit.
Local `--include-untracked` additionally covers every nonignored new file. Nested
archives and tracked dotfiles are included. Historical exposure remains pending.

The active Alembic config now has no hardcoded sample URL. `alembic/env.py` already
supplies the synchronous DSN from environment-backed settings before either online
or offline migrations; removing the unused template does not introduce a fallback.
Active `.env.example` secrets are empty under the setup owner's changes. A scanner
regression now ensures an empty assignment cannot consume the next environment
line as its value. Frozen sample configuration bytes were preserved unchanged.

## Initial containment record

| Item | Verified result |
|---|---|
| Original tracked campaign | 6,470 files |
| Actual receiver credentials | **71 nonempty files, each 64 bytes; 4,544 bytes total** |
| Private preservation | 71 exact-byte copies; source readback and later `HEAD` comparison all match |
| Permissions | Every copied file/manifest/receipt `0600`; every newly created directory `0700` |
| Active-tree removal | Exactly the 71 manifest-listed `receiver-token` files deleted using `apply_patch` after preservation passed |
| Remaining campaign | **6,399 files, 1,317,459,480 bytes**; campaign diff contains only credential deletions |
| Admission/config screening | **289 files / 115,361 bytes; zero findings**, including matching against every removed token |
| Full remaining-campaign scan | 6,399 entries, all bytes inspected; **zero known receiver-token findings** |
| Synthetic fixtures | Nine exact-path/full-SHA256-pinned test sources recognized; no directory-wide exemption |
| Export execution | Four selected results, **343,530 payload bytes**, exact-byte copies with manifest |

The receiver loads the credential with `protected_read`, requires length 64 and
authenticates requests against it (`emulation/experimental_lab_receiver.py`). These
were real receiver authentication values, not synthetic test fixtures. No raw values
are included in this handoff or scanner output.

### Private preservation location

`ai-engine/artifacts/adr027-evidence-private-20260921-001/`

- Existing `ai-engine/.gitignore` excludes the artifact store; `git check-ignore`
  verified the new destination before writing.
- Original repository-relative paths are retained under that private directory.
- `manifest.json` records each relative path, byte count and SHA-256.
- Manifest SHA-256:
  `ecce2afc4524cc061a5a3d86b542cd6cb0bc6ade58f1a2c97513d6f8474e8547`.
- `preservation-complete.json` records the successful source comparison, counts and
  manifest hash. Verification checks the receipt as well as file hashes/permissions.
- `campaign-scan-001.json` retains the initial conservative scan findings. Later
  scanner refinements distinguish code references/hash maps from credential values;
  the final scan result is described below.

The parent artifact store retains its pre-existing permissions. Its new private
child is `0700`, preventing other users from traversing to the copied credentials.
Neither the private copy nor current-tree deletion establishes revocation.

### Other campaign admissions/configuration

Reviewed: one parent admission, 71 bootstrap admissions, 71 campaign admissions,
71 run child admissions, four recovery child admissions and 71 child configs.
These contain approval flags, scope/times, identities, hashes and configuration;
no receiver-token copies or additional credential findings were identified.
The six nested `source/deploy/state/adr023-private-evidence/*/backup/manifest.json`
files contain SHA-256 values keyed by secret-file locations, not raw secrets.
Those records and genuine measurement data remain intact.

The initial full campaign scan intentionally **exited 1**, with three conservative findings:

1. `source/backend/alembic/alembic.ini`: historical development credential URL.
2. `source/backend/docker-compose.yml`: historical development password defaults.
3. `source/deploy/entrypoint.py`: a secret mount-name mapping (reviewed non-secret
   reference, still conservatively reported by the generic assignment rule).

These are frozen source files, not additional receiver credential files. The CI
follow-up above explicitly reviewed and hash-pinned them as frozen public samples
or non-secret references. Active setup repairs remain R05-owned. This scan policy
does not authorize exporting frozen defaults as production configuration.
The nine synthetic exceptions cover frozen deterministic auth/SNMP/DSN tests and
negative secret-screening tests. Each exception requires the exact path and complete
file hash, suppresses only named rules, and cannot suppress a known receiver token.

## Reusable tool contract

Python standard library only; reuses `deploy/release_manifest.py`'s existing safe
directory handling, canonical JSON and atomic no-clobber publication primitives.

- `scan`: all selected files regardless of extension, including extensionless
  receiver tokens; known-private values are matched even inside arbitrary binary
  content and filenames. Reports rule codes and SHA-256 of logical paths only.
- Detects credential fields, assignments, bearer/JWT values, credential URLs and
  private-key markers; parses JSON, JSONL and JSON embedded in transcript strings.
  Python variable references and secret-path checksum maps are not credential values.
- ZIP, TAR, gzip, bzip2 and xz are inspected recursively by magic bytes, including
  extensionless/nested containers, without extraction. Unsafe/duplicate paths,
  links/special members, encrypted ZIPs, malformed/unsupported archives and exhausted
  budgets fail closed. Defaults: 64 MiB/file or decompressed member, 4 GiB cumulative
  inspected bytes, 50,000 entries, five archive levels and 200:1 expansion; xz decoder
  memory is separately bounded to 64 MiB. Nested bytes count again toward the budget.
- `export`: requires an explicit exact-path allowlist with SHA-256 and byte length;
  refuses private/admission/config/credential paths, including inside archives.
  Screens every selected byte before creating output. No fixture exemptions apply.
  Sanitization selects/omits files; it never rewrites measured evidence bytes.
- Export rejects traversal, source/output overlap, symlink ancestors, hardlinks,
  special files, changed source pins and existing destinations. Outputs use protected
  directories/files and atomic no-clobber writes, fsync and byte readback.
- `preserve-credentials`: requires the expected 71 tracked receiver files, the
  existing ignored artifact store and a new destination. Copies and verifies only;
  it never deletes credentials or edits Git history.
- `verify-private`: rechecks inventory, exact hashes, receipt and permissions.

### Commands for integration

From the repository root:

```sh
python -m unittest discover -s scripts -p test_evidence_hygiene.py -v
python -m unittest discover -s scripts -p test_preserve_qualification_evidence.py -v
python scripts/evidence_hygiene.py verify-private --destination ai-engine/artifacts/adr027-evidence-private-20260921-001
python scripts/evidence_hygiene.py scan --root . --tracked --fixtures security/evidence-fixtures.v1.json --known-private ai-engine/artifacts/adr027-evidence-private-20260921-001
```

`--tracked` scans current working-tree content and excludes Git-reported pending
deletions. It does not scan Git history or untracked files. For a standalone export
directory, omit `--tracked` to traverse every file. A CI checkout will not contain
the private backup: omit `--known-private` there; receiver filenames/structured
credential detection and archive inspection still work. The private lookup extends
detection to copies of the 71 known values at arbitrary locations.

Optional `--fixtures FILE` supplies scan-only exceptions as reviewed explicit
entries using schema `nanfo-synthetic-fixtures-v1`: `files` maps exact logical paths
(archive levels separated by `!/`) to `{sha256,rules,reason}`. Values are never
listed in an exception. Modified bytes invalidate it. Do not convert scan failures
into a blanket successful CI result. The completed whole-tree review and local
passing gate are recorded above; policy updates require reviewing changed content.

Export allowlists use schema `nanfo-evidence-allowlist-v1`, with `files` mapping each
explicit source-relative path to `{bytes,sha256}`. Prepare/review those pins first:

```sh
python scripts/evidence_hygiene.py export --root nanfo-experimental-campaign-014 --allowlist /absolute/path/to/reviewed-allowlist.json --destination /absolute/path/to/new-export --known-private ai-engine/artifacts/adr027-evidence-private-20260921-001
```

Executed export:
`ai-engine/artifacts/adr027-sanitized-export-20260921-001/`, selecting only
`result.json`, `cleanup.json`, `campaign-evidence.json`, `offline-gates.json`.
`export-allowlist.json` retains the exact executed selection; `manifest.json` pins
the exported payload. Manifest SHA-256:
`c0bdca8f2372758506983d8114b8155dc6c17dbf6848f2c102f26c2b094f4beb`.
This compact export retains historical failed/incomplete outcomes; it does not
assert successful scientific qualification or relocate every referenced artifact.

## Validation and remaining remediation

- Focused hygiene tests: **17 passed**. Covers exact-byte/no-secret exports,
  no-clobber, pins, paths, links/FIFOs, permissions/tampering, escaped/embedded
  credentials, extensionless/nested containers, archive bounds/encryption,
  synthetic-fixture restrictions and secret-free diagnostics.
- Existing preservation regression suite: **11 passed**.
- From `backend/`: `poetry run ruff check ../scripts/evidence_hygiene.py ../scripts/test_evidence_hygiene.py`.
- Full campaign scan: 349.4 seconds; 6,399 entries, nine synthetic fixture matches,
  three retained triage findings above. An earlier 120-second invocation timed out;
  the completed scan is the result quoted here.
- Private readback and Git `HEAD` byte comparison: **71 matches, zero mismatches**.
  Git campaign diff inventory: exactly the 71 credential deletions, zero other
  campaign changes. Active receiver files: zero. Git index/history still contain
  the original values until separately authorized staging/commit/history work.

Remaining operator/coordinator work:

1. Confirm the exposed values were never reused; invalidate any surviving receiver
   or copied authority. Historical cleanup reports are not independent revocation
   proof, and no live-authority claim was made here.
2. Review repository visibility, clones, forks, caches, CI artifacts and historical
   archives for exposure. Coordinate any credential rotation and notifications.
3. Plan an explicitly authorized history-cleanup operation after private retention
   and collaborator coordination. Current-tree deletion alone does not remove
   historical exposure. No history rewriting, commits or force pushes occurred.
4. Run the delivered dedicated workflow remotely and require its check through
   branch protection. Review any new or changed findings before updating exact
   policy pins. Publish only reviewed allowlisted evidence; retain raw credentials
   and private originals in protected storage.

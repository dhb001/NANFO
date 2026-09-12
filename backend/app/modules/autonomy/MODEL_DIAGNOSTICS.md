# ADR018 Model Diagnostics

Backend-only historical inference, independent of configuration, overrides and the
autonomy worker. No events, live observer, training, safety approval or dispatch.
Migration `0016_model_diagnostics.py` follows the separately owned `0015` and owns
only `autonomy_model_diagnostics`. UPDATE/DELETE are rejected by a database trigger.

## Frontend Contract

Schema source: `backend/app/modules/autonomy/model_diagnostic_schemas.py`.
Router: `backend/app/api/v1/model_diagnostics.py`, mounted separately in `app/main.py`.
OpenAPI: `/api/openapi.json`, concrete `ModelDiagnosticsResponse`,
`RegisteredModelStatus`, `DiagnoseModelRequest`, `ModelDiagnosticRecord`,
`DiagnosticResult` component schemas. No frontend files changed.

- GET `/api/v1/autonomy/model?network_id=UUID&history_limit=20` returns
  `success/data/meta/errors`; `data` has scoped model metadata, allowlisted
  `history_references`, bounded diagnostic records and explicit unavailable-live status.
- POST `/api/v1/autonomy/model/diagnose` accepts ONLY
  `{"network_id":"UUID","history_reference":"validation-06"}` and returns 201
  with `data: ModelDiagnosticRecord`. Model/checkpoint IDs are selected server-side
  from the one registered model for that network, never caller paths or vectors.
- Each record contains diagnostic/network/workspace/actor/time identity plus
  `result`: action and historical action path, two finite normalized probabilities,
  finite value, measured observation echo, input/history/source/policy/weights/registry/
  contract/spec hashes, inference/validation/subprocess durations, and scoped
  operator-attested benchmark metadata with evidence digest.
- `live=false`, `execution=not_applied`, `safety_authorized=false` and
  `probabilities_are_safety_confidence=false` are constants. Probabilities are NOT
  calibrated safety confidence. The action path is historical model output, not a
  proposed live command. Successful replay never updates the autonomy provider.
- Errors: 401 unauthenticated; 403 current permission/membership denied; 404 unknown
  network-scoped history; 409 scope/registry changed during inference; 422 invalid
  payload; 429 concurrent diagnostic; 503 missing/tampered/unavailable artifacts,
  sandbox/runtime failure or timeout. Failed inference does not create a fake record.

GET requires current `read:telemetry`. POST requires both current `write:config`
and `execute:rollback` plus writable current organization membership. Existing
token org/workspace constraints remain enforced. Model and history network allowlists
apply even to Admin; records always filter both network and workspace. Authority
and registry pin are checked again after subprocess completion.

## Deployment Settings

No settings class, `.env`, override or deployment configuration was edited.
Set these four variables in the protected backend service environment:

| Variable | Meaning |
| --- | --- |
| `NANFO_MODEL_REGISTRY` | Absolute protected operator JSON registry path, outside model/producer root |
| `NANFO_MODEL_REGISTRY_SHA256` | Exact lowercase SHA256 of registry bytes, provisioned independently of producer |
| `NANFO_MODEL_ROOT` | Absolute read-only source/checkpoint/history/evidence root |
| `NANFO_MODEL_PYTHON` | Absolute trusted AI `.venv/bin/python`, exact checkpoint runtime |

The entrypoint is fixed to `backend/scripts/frozen_model_diagnostic.py`, not configurable
by registry or requests. Deploy `backend/scripts/` with the backend; the AI interpreter
needs the checkpoint's exact torch/numpy/gymnasium/Python versions and Pydantic.
Native Linux x86_64, Landlock ABI >= 5 and `libseccomp` are required. The tested
kernel reports ABI 10. Unsupported architecture, disabled/missing Landlock or any
ruleset installation failure fails closed before frozen import; no fallback or
caller-supplied sandbox paths. Python >= 3.12 is required for the entrypoint.
Run backend and child
as a non-root service account with no producer write authority. Registry and ancestors
must have trusted ownership and no group/world write (root sticky `/tmp` is allowed
for private disposable tests). Provision registry read-only and independently from
the artifact producer. The SHA pin prevents a changed registry being accepted even
when producer and operator were the same local user during verification.

Private registry schema is `ModelDiagnosticRegistry` in the same schema file:
`version:1`, `models` with model/checkpoint IDs, explicit network UUID lists,
`checkpoint:{path,sha256,size_bytes}`, `source_directory`, complete
`source_sha256:{filename:sha256}`, `histories:{ID:{artifact,network_ids}}`, and
`benchmark:{status,scope,limitations,evidence:{path,sha256,size_bytes}}`.
Artifact paths are relative to the configured root. The benchmark is an operator
attestation to pinned historical evidence, not a new qualification computation.
GET's `operator_registered` is registration, not a promise that today's runtime or
files pass validation; POST performs that validation afresh.

Read-only incumbent references used in verification:

- Model `adr014-incumbent`, checkpoint `train-06`:
  `artifacts/adr014-001/train-06/checkpoint.ptz`, SHA256
  `5b8818af655ec8efce5d3bc3def27db599f3e0df379a0ae263dcefb5f72a80a5`.
- Source: `artifacts/adr014-001/source`, exact complete source map in the checkpoint
  manifest. No source check replacement, loader fallback or pickle allowlist additions.
- History ID `validation-06`: `artifacts/adr014-001/validation-06/last-history.json`,
  SHA256 `1ed5856374244fc1a547b05043f5c7f05d5a2da89a285fd27ec09186ba3123b7`.
  History wrapper version 3 contains actual version-4 measured drain evidence.
- Benchmark evidence: `artifacts/adr014-holdout-001/test-report.json`. Scope is
  reserved 12 seeds, balanced stationary 2/20 Mbps impairment versus nominal-cost
  OSPF, not capacity-aware OSPF or arbitrary network superiority; ICMP RTT only.

## Isolation And Bounds

ArtifactStore opens each path component with `O_NOFOLLOW`, hashes the consumed
descriptor bytes and bounds input sizes. Verified source and artifacts are copied
unchanged into a private temporary working directory, closing source/checkpoint
hash-to-import races. The original source's `loadCheckpoint` uses restricted
`torch.load(weights_only=True)` and validates exact runtime, complete source map,
tensor shape/finite values, original manifest and measured training provenance.
The original `cli.main(infer)` validates full measured history/spec/image/distribution
and runs deterministic inference; no hand-built observation vector is substituted.

Child starts with `-I -B`, private HOME/TMPDIR/cwd, no inherited PATH/PYTHONPATH,
cloud/DB/JWT/Redis credentials or stdin. Seccomp denies native network/socket access,
exec, fork/vfork, process-mode clone, clone3, namespace creation, signal/process
inspection, io_uring and shared-memory/control IPC before frozen imports. Native
pthread clone is permitted only with CLONE_VM/SIGHAND/THREAD; clone3 returns ENOSYS
for pthread fallback. Metadata mutation syscalls are denied as well.
Limits: 30s parent wall timeout,
25s CPU, 8GiB address space, 64 descriptors, 64MiB file size, no core dumps, one
compute thread, 64KiB per output stream. Cancellation/timeout/output overflow kills
and reaps the child. Redis serializes inference across API processes with a fixed
40s lease and no waiting queue; Redis failure fails closed.

Landlock handles all filesystem access rights through ABI5 (including REFER,
TRUNCATE and device IOCTL), with no grants for execution/device creation. Filesystem
content access defaults to deny even for the backend's own UID. Read-only grants
cover the configured interpreter's stdlib/site-packages, exact shared-library files
from standard library locations, `/etc/ld.so.cache`, `/dev/urandom`, `/proc/cpuinfo`,
`/proc/meminfo`, and the new private staged evidence tree. No directory-wide `/usr`,
`/lib`, `/proc`, `/run`, home, backend or producer-root grant exists. In particular,
`/proc/self/root`, `/proc/self/fd`, `/proc/self/mem` and `/proc/self/environ` are not
readable. Interpreter library directories must contain only trusted runtime code,
never credentials or control mailboxes.

Only the staged tree's separate `scratch/` child permits ordinary file/directory
creation, read/write, rename and removal. HOME/TMPDIR/cwd point there. Checkpoint,
history and source remain read-only. Rules are irreversible and inherited by native
threads. Landlock's metadata-query limitations do not grant file contents or control
writes; metadata-changing syscalls are separately denied by seccomp. The unrestricted
parent deletes its private temporary tree after the child exits, since the child
cannot delete its own read-only evidence. Deployment still runs as non-root with no
inherited control descriptors; subprocess startup passes only stdin/stdout/stderr.

## Verification

Commands from `backend/`:

```bash
env -u VIRTUAL_ENV PYTHONPATH=.:.. /path/to/backend-venv/bin/python -m pytest tests -q --no-cov
env -u VIRTUAL_ENV PYTHONPATH=. /path/to/backend-venv/bin/python scripts/verify_model_diagnostics.py
```

The verifier uses existing Settings credentials in memory to create a random
disposable PostgreSQL database, migrates through 0016, seeds a generated-password
user/network fixture, uses real login/JWT/current identity and membership code
through authenticated ASGI HTTP, then drops only its owned database. Redis sessions
and locks use a real UUID-owned `redis:7-alpine` container, a random loopback-only
port and generated password in a private read-only mounted config. The verifier uses
the already installed image (`--pull=never`), drops container capabilities, runs it
non-root/read-only with resource bounds, and removes only that exact container.
No shared Redis keys, sessions, stream drains or flushes are used. Docker exists only
in this opt-in verifier, never in the diagnostic child. API auth is not overridden;
only DB and Redis dependencies use disposable
resources. App lifespan is intentionally not started, so unrelated workers cannot run.

Actual verification reproduced action 0, probabilities
`[0.9718289375305176,0.028171034529805183]`, value `3.2172513008117676`, input hash
`ea3a62d0a12bbc608b75b49b10a294bbcaeb2ec9ce276f07965d490352c5729a`.
Two new immutable records matched exactly except IDs/timing. Runtime inference
was about 1ms and full child wall time about 2.8s, not production forwarding latency.
Checks include tampered source/checkpoint/history, traversal, vector-only and
inconsistent measured evidence rejection, cross-network Admin isolation, role and
membership revocation, concurrency rejection, post-offload authority checks, bounded
output/timeout/cancellation and original source preservation.
`tests/unit/test_model_diagnostic_confinement.py` uses actual native syscalls against
same-UID private canaries to verify reads/writes/create/truncate/unlink/chmod/rename/
hardlink escapes, backend source access and `/proc` bypasses fail, while staged
reads, scratch writes and native threads succeed. Exec/socket/fork/clone/process IPC
denials are actual kernel results, not monkeypatched Python calls. No live observation
compatibility, production safety or dispatch readiness was asserted.

Final confinement verification: full backend suite **1858 passed, 50 skipped**;
scoped Ruff **0.15.6 passed**. Explicit backend interpreter used:
`/home/DHB/.cache/pypoetry/virtualenvs/nanfo-backend-9hkWDLkY-py3.14/bin/python`
(there is no `backend/.venv` in this checkout). Ruff was installed only into that
existing backend environment; no dependency/configuration/lockfile was changed.
The neural subprocess still uses the registry-configured original AI Python 3.12
runtime, not the backend interpreter. Final real Redis/authenticated DB run:
inference `0.001090007s`, child wall `2.879467696s`, exact two-record replay.

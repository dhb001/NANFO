# ADR022 — Non-actuating AI operator runtime

## Delivered software and boundary

`ai-engine/scripts/agent_runtime/` is a runnable operator runtime, using the real
ADR021 shadow schemas and capacity/failure/policy analyzers. It adds a typed
permission-scoped registry, serial deadline scheduling, evidence-weighted
coordination, persistent four-tier SQLite memory, checkpoint recovery, immutable
decisions and an append-only audit chain. No frozen training source, checkpoint,
artifact, dependency, backend provider/API, or application composition changes.

Owned sources: `__init__.py`, `__main__.py`, `contracts.py`, `registry.py`,
`scheduler.py`, `memory.py`, `runtime.py`; tests: `tests/test_agent_runtime.py`.
Authority: ADR022 Agent execution, ADR021, ADR018 diagnostic export contracts and
ADR012 qualification/calibration/authorization separation. Existing shadow handoff:
`AIShadow.md`.

This implementation is deterministic Python plus SQLite, not an installed
LangGraph/LLM system. Its agent registry is an **analyzer permission registry**,
not a qualified inference-model registry. Declarations cannot install qualified
models, a compatible live observer, calibrated safety bounds, an executor or
recovery provider. These remain explicit unavailable providers in exported records.

## Executable reasoning workflow

1. **Observe:** validate pinned registry/request and scope, then consume the existing
   pinned plan, backend diagnostic export, matched outcomes and original benchmark
   through `shadow.io.loadEvaluation`. Reuse exact model/input/provenance and
   baseline-comparability checks. Never run inference or collect telemetry here.
2. **Options:** retain hold-and-review plus OSPF, both constants and heuristic
   alternatives from the actual shadow decision. Retrieve bounded scoped memory.
3. **Model evidence:** retain the frozen checkpoint identity and paired descriptive
   outcomes. The three existing analyzers inspect compatible diagnostic evidence;
   held-out outcomes and historical memory never enter their context or tune them.
4. **Recommend:** coordinate the registered analyzers in stable lexical ID order.
   Each produces a typed outcome (completed, denied, timeout, error, unavailable).
   Consensus retains every finding, dissent and baseline alternatives.
5. **Execute:** explicitly unavailable. No physical command, process executor,
   runtime plugin, dynamic import, network client or activation interface exists.
6. **Reflect:** persist a typed immutable decision, then a long-term reflection
   with the same scoped provenance and original evidence expiry, transactionally.
   If evidence is expired or future-dated, retain the decision/audit but create no retrievable
   fresh reflection. Reflection never updates weights or trains a model.

Memory is useful review context: decision records include exact retrieved memory
IDs and hashes, and the `retrieve` command exposes their source-linked summaries.
Historical incident text cannot override validated diagnostic facts or safety
gates. Semantic memory holds explicit graph object references; there is no graph
database traversal, inferred topology, embedding search or fabricated RAG provider.

## Invocation and operator contracts

From **`ai-engine/scripts/`**, with the existing AI interpreter:

```bash
../.venv/bin/python -B -m agent_runtime --help
../.venv/bin/python -B -m agent_runtime run-once \
  --registry /operator/runtime/registry.json --registry-sha256 "$REGISTRY_SHA256" \
  --request /operator/runtime/request.json --request-sha256 "$REQUEST_SHA256" \
  --database /operator/runtime/memory.sqlite \
  --plan /operator/shadow/plan.json --plan-sha256 "$PLAN_SHA256" \
  --diagnostic /operator/shadow/diagnostic.json \
  --outcomes /operator/shadow/outcomes.json --benchmark /operator/shadow/benchmark.json
```

The database parent must already exist. Use a protected operator-owned directory.
No `PYTHONPATH`, backend installation, historical training artifacts or new library
is needed. This is a source-checkout entrypoint, not a frozen wheel modification.

Commands share the required registry/request paths and independent byte pins:

| Command | Additional inputs / result |
|---|---|
| `ingest` | Database and request `item`; append one validated memory record |
| `retrieve` | Database; bounded unexpired scoped memory selected by tiers/session |
| `analyze` | Five shadow evidence options above; analyze/export without SQLite writes |
| `run-once` | Database + shadow evidence; claim, checkpoint, coordinate, reflect, persist |
| `export` | Database + exact run ID/scope; return immutable historical decision |
| `audit` | Database + optional `--after` nonnegative sequence; <=50 scoped chained events |

Exit 0: completed operator operation; exit 2: valid analysis with abstaining
consensus; exit 1: sanitized validation/permission/storage rejection on stderr.
Decisions are JSON on stdout. Historical `export` is not a refreshed analysis;
its embedded evaluation time and evidence expiry remain unchanged. A repeated
`run-once` with identical input pins returns the original immutable decision;
use a new run ID for a new review. Changing scope changes the complete identity.

### Registry v1

Fields are `version:1`, `operator_id`, `expires_unix`, nonempty `scopes`,
`permissions`, and `agents`. Permissions are exclusively `analyze`, `run`,
`memory_read`, `memory_write`, `export`. Every operation checks registry expiry,
scope and permission; run-once requires all five. Every checkpoint and final
write rechecks permission and the run-generation fence.

Each scope has:

```json
{
  "tenant_id": "00000000-0000-0000-0000-000000000002",
  "network_id": "00000000-0000-0000-0000-000000000001",
  "model_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "trace_id": "trace-1"
}
```

`tenant_id` maps to the existing backend/shadow **workspace_id**. It is a local
operator field, not a new backend tenancy contract. Runtime evidence binding checks
workspace, network and frozen policy hash against the actual shadow plan.

Agents have `agent_id` (`capacity`, `failure`, `policy` only), `version:1`, explicit
`scopes`, `tools`, `timeout_seconds` (>0, <=2; default 0.5). Agent scopes must be a
subset of the operator scopes. Capacity/failure require `read_observation`; policy
requires `read_review_policy`. No other tools are accepted. Missing grants yield a
denied finding rather than invoking an analyzer. Policy gets no observation tuple;
capacity/failure receive no diagnostic action or permitted action list.

### Request v1

Fields: `version:1`, `scope`, `session_id`, `run_id`, optional `retrieval_limit`
(1–50, default 10), `tiers` (default all four), and `item` (memory ingest only).
All schemas forbid extra fields, nonfinite numbers, invalid IDs/hashes and
unrecognized agent/tool names. The request byte hash is operator-supplied; registry
and request pins must come from a trusted source, not merely accompany untrusted
input. SQLite file access and trusted operator configuration are the authority
boundary, not a substitute for backend RBAC or filesystem multiuser isolation.

Print the exact machine-readable local schemas from `ai-engine/scripts/`:

```bash
../.venv/bin/python -B -c 'import json; from agent_runtime.contracts import Registry, Request, MemoryItem, RuntimeDecision; print(json.dumps({c.__name__: c.model_json_schema() for c in (Registry, Request, MemoryItem, RuntimeDecision)}, indent=2))'
```

## Memory and immutability

Every memory item contains `memory_id`, the full `scope`, `session_id`, `tier`,
`kind`, bounded `summary`, 1–16 `provenance_sha256` references, `source_reference`,
`source_observed_unix`, `source_expires_unix`, `created_unix`, `ttl_seconds`, and
optional `graph_references` (semantic only, <=32). Timestamps are finite UTC Unix
seconds. A source cannot be acquired after creation or expire before creation.
Expiry is exclusive: `min(source_expires_unix, created_unix + ttl_seconds)`.

| Tier | Concrete behavior |
|---|---|
| `working` | Session-local; exact session match; TTL <=1 hour |
| `short_term` | Scoped telemetry/observation notes; TTL <=1 day |
| `long_term` | Incident or reflection records only; bounded TTL <=1 year |
| `semantic` | Explicit graph-reference records only; nonempty references; bounded TTL <=1 year |

All tiers retain tenant/network/model/trace scope. Other sessions may retrieve
non-working records only within that exact scope. Queries apply scope, expiry,
session and tier restrictions **before LIMIT**, then deterministic creation/ID
ordering. Returned rows are hash-verified and their body scope/expiry rechecked.
Unknown or unauthorized scopes cannot enumerate other records, decisions or audit.
Source expiry applies to all tiers, including long-term and semantic.

SQLite schema v1 has `memory`, `audit`, `runs`, `checkpoints`, `decisions`. Records
are bounded to 512 KiB; each table has a 10,000-row admission ceiling, and SQLite
has a 16,384-page limit (64 MiB at default 4 KiB pages). Capacity failure rolls back;
there is no silent eviction of audit or evidence. Operators must archive/migrate
closed stores when full. Expired memory is excluded from retrieval but retained
as immutable historical records. Automated retention/deletion is not implemented.

Memory, checkpoint, decision and audit tables reject UPDATE/DELETE with SQLite
triggers. Only the internal run lease/state index mutates. Audit events carry
scope, run, kind, time, prior event hash and canonical content hash; scoped bounded
audit exports verify the chain. SQLite transactions make admission, checkpoint,
completion and reflection writes atomic. New DB files use 0600; symlinks,
nonregular files, other owners and group/world access are refused. Unsupported
schema versions fail closed. This is not encrypted storage or cryptographically
authenticated protection from a malicious filesystem owner who can rewrite DB
files/triggers; provision private directories and retain trusted export hashes.

## Scheduling, consensus and recovery

- Fixed pure Python analyzers run serially in lexical order with per-agent POSIX
  `setitimer` deadlines, plus a six-second total analyzer budget. Requires the main
  thread and an unused process alarm; otherwise records an error. Existing signal
  handlers are restored. No uncancellable worker threads or subprocess executors.
  This platform limit is intentional for the supported Linux operator CLI.
- Exceptions and timeouts become bounded typed outcomes with stable reason codes;
  raw exceptions are not exported. Interrupted process/keyboard termination leaves
  an unfinished claim/checkpoint history that can recover after its 30-second lease.
- Each claim binds registry pin, full request and frozen plan pin. A competing claim
  before expiry fails busy. After expiry, generation increments; old generations
  cannot write. Recovery reuses immutable successful **or failed** checkpoints and
  runs only missing analyzers, without tune-until-success retries.
- Memory retrieval is checkpointed once; on restart expired entries are removed,
  not replaced by newly available material. Diagnostic hashes are revalidated and
  shadow freshness is recomputed before completion. Exact completed replay returns
  the original historical record rather than silently refreshing acquisition time.
- Consensus weight is the count of complete relevant observed fields: capacity up
  to four (two capacities/two utilizations), failure up to two (loss/RTT), policy
  one (bound review action membership). Unavailable/failed/denied evidence has zero
  weight. Review versus observe counts determine posture; a tie requests review.
  Missing mandatory agents or shadow abstention forces abstention.
- All original findings and opposite-posture dissent are retained, including a
  minority failure warning when capacity evidence dominates the count. Any warning
  adds `investigate_flagged_evidence`; all original baseline/hold alternatives remain.
  Weights are descriptive evidence coverage, not independent votes, calibrated
  confidence, safety probability, model qualification or deployment approval.

Every decision embeds the existing typed shadow `Decision`, agent outcomes,
consensus, retrieved memory IDs/hashes, input/registry hashes, workflow and reflection.
Execution stays `not_applied`, safety/production/online-learning flags stay false,
and consensus safety confidence stays null.

## Verification and acceptance

Run from `ai-engine/`:

```bash
.venv/bin/python -m pytest tests/test_agent_runtime.py -q
.venv/bin/python -m pytest -q --tb=short
.venv/bin/ruff check scripts/agent_runtime tests/test_agent_runtime.py
.venv/bin/ruff format --check scripts/agent_runtime tests/test_agent_runtime.py
```

The artifact-free subprocess example is
`test_runtime_cli_clean_checkout_all_commands_and_restart`: only new runtime/shadow
source is copied into a clean directory; fixture evidence is pinned; all six CLI
commands execute with no PYTHONPATH/provider configuration. Two separate run-once
processes and export must return the identical persisted decision. Its model and
measurements are explicitly synthetic software fixtures, not calibrated acceptance.

Coverage includes every scope dimension, session isolation, all tier TTL/source
expiry boundaries, bounded retrieval, malformed registry/tool denial, immutable
records, tamper detection, quota rollback, POSIX timeout/error handling, deterministic
coordination, dissent/ties, cross-scope exports, lease takeover/fencing, crash/restart
checkpoint reuse, expired-memory exclusion, stale-evidence abstention, and explicit
socket/subprocess/training-import traps. No live training or lab measurement.

Verification results: full AI suite **463 passed** (previous shadow-only baseline
433); runtime suite **30 passed**. One existing Gymnasium infinite observation-space
bound warning remains. Scoped runtime/shadow lint and format and whitespace checks
pass. Frozen `ai-engine/src`, artifacts, dependency manifest and lock diff are empty.

This closes the software registry/scheduling/persistent-memory/coordination gap
for operator decision support. Remaining acceptance includes authentic operator
registry provisioning and actual evidence normalization audits, sustained operator
deployment/storage lifecycle review, and the separate absent qualified inference,
runtime compatibility, physical calibration, executor and recovery providers.
It cannot activate P3 production autonomy, and does not claim LangGraph, LLM agents,
physical causality, RAG/Neo4j installation or measured safety.

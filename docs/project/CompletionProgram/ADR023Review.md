# ADR023 independent security/correctness review

Date: 2026-09-20. **Final independent disposition: all11 findings closed in the
reviewed source; the associated privileged-import observation is also resolved.**
Scoped software review approved. Live deployment, aggregate execution timing and
physical safety qualification remain external acceptance obligations.

## Final closure register — findings1–11

| Finding | Status |
|---|---|
|1: permanent fanout poison cancels leadership|Closed; safe quarantine/confirmation assertions pass.|
|2: executable plan not independently bound|Closed; reviewed-plan/mapping and descriptor-trust assertions pass.|
|3: qualified total delay widened|Closed; bounded total and exclusive expiry assertions pass.|
|4: Core observation reference pin bypass|Closed; pin-before-insert and owner-scope refusal assertions pass.|
|5: receiver row-lock authorization gap|Closed; post-lock revocation refuses commit.|
|6: incoming duplicate bytes fan out|Closed; canonical replay, hidden-field exclusion and tombstone suppression pass.|
|7: archive ancestor substitution|Closed; substitution refuses before deletion; unchanged restart reads exact bytes.|
|8: FRR inventory after final checkpoint|Closed; both add/remove paths retain final-check-before-I/O ordering.|
|9: readable health signing key admitted|Closed; confidential descriptor admission independently verified below.|
|10: receipt expires during TTL read|Closed; authenticated expiry evaluated after all awaits; acceptance refuses.|
|11: config reload retains stale health policy|Closed; complete config identity change fails closed, including after staging.|

### Independent final check of health/config/import corrections

Read the latest owner response and current implementations, then replaced the
three remaining defect-positive reproductions with safe assertions in
`/tmp/opencode/adr023_client_review.py`. Scope stayed on the same trust paths.

- **Finding9:** `execution_settings.py:51–52` now delegates to
  `health_secret.py:18–47`. The secret reader walks no-symlink directory descriptors,
  requires a single-link regular key owned by root/current service with exact0600,
  checks length/hash on the descriptor actually read, and checks its protection
  again afterward. Independent cases reject0644/0640/0660/0400 and accept the exact
  pinned0600 key. Owner regressions additionally exercise alias/ancestry/owner and
  chmod-during-read refusals. Public evidence permissions are not used for secrets.
- **Finding10:** `receiver_health.py:32–55` bounds GET+TTL to2s and evaluates the
  signed timestamp after both awaits, with no later I/O. The original deterministic
  replacement-during-TTL reproduction now raises `invalid_or_stale`. An independent
  acceptance test introduces that same expiry after staging; acceptance raises
  `not_ready_after_staging` and never commits the caller transaction.
- **Finding11:** `execution_client.py:94–108` binds config pathname, configured byte
  pin and canonical complete config digest. Reload rejects any change before using
  the old policy. `refresh_status()` clears cached readiness first (`44–57`);
  acceptance calls it again after staging (`64–71`). Independent cases refuse changed
  freshness, resource, config path and pin; unchanged config remains ready. A config
  change during staging also refuses acceptance without committing. This explicitly
  requires recreating the client/process to adopt a newly reviewed config.
- **Import observation:** `frr_contract.py:10` now uses the pure
  `emulation/autonomous_contract.py`. A fresh independent interpreter imports the
  actual journal client, settings, providers and FRR schema together: none of
  `autonomous_frr`, `autonomous_namespace`, `autonomous_driver`, `ospf`, `actions` or
  `runner` is loaded. The pure constants module is loaded. The runtime source
  fingerprint list includes both new contract and secret-reader files.

**Final offline gate:335 passed in14.88s** —273 owner regressions and62 independent
safe-behavior tests (26 original review,12 FRR,24 client/health). All three temporary
review files now assert safe behavior; no defect-positive assertion is counted as
acceptance. Existing exact-recovery filtering, health forgery/scope/replay refusal,
post-stage health/authority refusal, and driver mutation-ordering tests remain green.

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend:. \
  /home/DHB/.cache/pypoetry/virtualenvs/nanfo-backend-9hkWDLkY-py3.14/bin/python \
  -m pytest -q -c /dev/null -p no:cacheprovider --asyncio-mode=auto \
  -W ignore::DeprecationWarning \
  backend/tests/unit/test_execution_client.py \
  backend/tests/unit/test_receiver_health_review.py \
  backend/tests/unit/test_autonomous_execution.py \
  backend/tests/unit/test_autonomous_frr.py \
  backend/tests/unit/test_autonomous_frr_startup.py \
  backend/tests/unit/test_autonomous_frr_final_checkpoint.py \
  backend/tests/unit/test_adr023_review_autonomy.py \
  backend/tests/unit/test_autonomy_service.py \
  /tmp/opencode/adr023_client_review.py \
  /tmp/opencode/adr023_review_repros.py \
  /tmp/opencode/adr023_frr_review_repros.py \
  --basetemp=/tmp/opencode/adr023-review-eleven-final
```

Owner-reported309 passes including36 real PostgreSQL cases remain attributed
evidence, not an independent infrastructure rerun. This final check performed no
namespace mutation, live lab, PostgreSQL/Redis connection, deployment or training.
Fixtures and in-memory transport establish software regression behavior, not genuine
calibration, guaranteed aggregate actuation duration or future receiver availability.
Updated source fingerprints still require review and source-matched live acceptance
before installation/activation. No application source edits or dependency installs;
only the independent temporary tests and this report were changed.

## Historical journal-client review and remediation evidence

The findings9–11 descriptions, defect-positive results and pending-sign-off wording
below record earlier review/owner stages. The final closure register and independent
safe gate above supersede those statuses; historical evidence is retained intact.

### Initial journal-client / receiver-health composition review

### Owner remediation9–11 and import boundary (pending independent sign-off)

*9:* `health_secret.read_health_secret` walks from `/` using directory-relative
`O_NOFOLLOW` descriptors, checks every ancestor's trusted owner/write protection,
and reads/hashes the **same** regular single-link key descriptor with root/current
service ownership and exact0600.0644/0640/0660/0400, symlink/ancestor-symlink,
foreign owner, writable ancestry, hardlink and chmod-during-read cases reject.
Public hash-pinned config/evidence may retain their existing nonsecret permissions.
Trusted root-owned sticky ancestors (e.g. `/tmp`) remain allowed by the established
protection policy; the key itself must always be0600.
*10:* GET and TTL run within one bounded2s timeout. Signed completed_at and scope/MAC
validation run **after both awaits**, with no subsequent I/O before return. A renewed
TTL cannot authorize expired older bytes. Acceptance's post-stage check uses the
same refreshed readiness path. No atomic snapshot claim: signed age is authoritative
regardless of which receipt the later TTL describes.
*11:* factory clients bind canonical complete config digest plus configured pathname
and expected byte pin. Reload rejects any difference (including freshness, resource,
roots/key paths or config location/pin) as unavailable; recreate the process/client
to admit the newly reviewed config. Matching installation/key alone is insufficient.
*Import boundary:* pure `emulation/autonomous_contract.py` holds the versioned
constants. Fresh interpreter imports of journal client/settings/providers/FRR schema
load none of autonomous_frr, autonomous_namespace, autonomous_driver, ospf, actions
or runner. Real driver checks its action map against the unchanged frozen PATHS.

Verification: **309 passed**, including the existing **36 real PostgreSQL cases**,
new deterministic races/secret-permission/import checks and owning regressions.
The supplied `/tmp/opencode/adr023_client_review.py` ten safe tests pass; three
defect-positive tests now fail with private-key rejection, stale-body rejection and
unavailable after config change. The import defect assertion now sees only
`emulation.autonomous_contract`. Original reviewer file preserved unchanged.
Scoped Ruff and whitespace checks pass. One load-sensitive subsecond FRR-success
fixture expired during24 real authority transactions; its synthetic lifecycle
horizon is now5s, while the dedicated subsecond expiry races remain unchanged.
No production threshold, calibration or evidence was widened/created.

Owned disposable PostgreSQL removed after tests. No privileged namespace/lab,
deployment-file changes, training or commits. Source fingerprint list includes the
new pure contract and secret reader; existing hashes cannot be reused without review.
Independent reviewer sign-off is still requested, not asserted by this owner entry.

Reviewed the latest `AutonomousExecution.md` composition contract and source path
from `installed_providers` through protected config, calibrated safety, journal
acceptance, receiver progress receipts and `recover --execution-id`. The earlier
eight fixes were not comprehensively reopened. This review used offline fixtures,
in-memory transport and a fresh import-only subprocess; no infrastructure ran.

### 9. P2 — Health signing key need not be confidential

**Location:** `backend/app/modules/autonomy/execution_settings.py:50–54`;
`backend/app/modules/autonomy/registry.py:18–24`.

The new secret-key loader uses `protected_path`, which prohibits untrusted writers
but allows group/world **read** bits. `ArtifactStore` verifies bytes/type/hash, not
secret confidentiality. A mode0644 `health.key` under mode0755 protected directories
therefore passes the actual loader. This is suitable protection for public pinned
evidence, but not for the HMAC secret introduced by this composition.

**Independent reproduction:**
`test_defect_world_readable_health_secret_is_admitted` writes a random32-byte key,
sets mode0644 and directory0755, and calls the real `ExecutionClientConfig.load()`
with only calibration admission replaced by a synthetic installation seam. The key
is accepted. A receipt manually signed using the readable key, without calling the
receiver's publisher or completing an iteration, makes `refresh_status()` ready.

**Preconditions/impact:** another identity must be able to traverse the deployed
key path, read it and submit the forged receipt through Redis write access. This is
not an unauthenticated HTTP exploit, nor does a health receipt override actor,
calibration or receiver dispatch checks. It defeats the intended separation between
arbitrary Redis writers and trusted receiver progress if key permissions are ordinary
0644 defaults. “Protected path” currently gives false assurance for this secret.

**Correction:** validate confidentiality on the same opened key descriptor that is
read/hashed: regular file, trusted owner, and no unintended group/other readability
(or an explicit trusted-group policy). Keep evidence-file rules separate. A hash
pin establishes key identity, not secrecy. Add rejection tests for0644/0640 keys
outside any explicitly approved sharing policy.

### 10. P2 — Health expiry is checked before a separate potentially blocking TTL read

**Location:** `backend/app/modules/autonomy/receiver_health.py:40–51`.

The authenticated `completed_at` age is checked at45, then `await redis.ttl(...)`
may wait before success returns. The TTL belongs to the current Redis value, not
necessarily the bytes obtained by the earlier GET. If another receipt replaces
the key during that wait, a valid positive TTL allows the **old, now-expired body**
to return successfully. There is no final clock check or atomic value/TTL read.

**Independent reproduction:**
`test_defect_renewed_ttl_cannot_make_read_body_fresh_but_is_accepted` publishes a
receipt at synthetic time1000 with max-age10. Inside the TTL transport call, time
advances to1011 and a new valid receipt is published. `check()` returns the original
1000 receipt even though its authenticated age is11 seconds. This uses deterministic
clock/transport doubles, no sleeps or real Redis.

`refresh_status()` separately recomputes remaining age and therefore refuses this
expired body, but the **post-staging acceptance check** at
`execution_client.py:65` calls `health.check()` directly and lacks that safeguard.
The following authority check checks authorization/certificate expiry, not health
freshness. This finding is stale health validation, not proof of unauthorized
device execution or that the newer receiver was unhealthy.

**Correction:** obtain receipt bytes/TTL together where practical and recheck the
authenticated timestamp after the last await before returning. A newer key TTL
must not validate an older body. Bound health I/O and test expiry during TTL waits
on the acceptance path.

### 11. P2 — Protected config reload silently keeps the old health policy

**Locations:** `backend/app/modules/autonomy/execution_client.py:44–51,89–94`.

The reload callback returns only `(installation, key)`; `refresh_status()` compares
those two values and discards the reloaded config's `health_max_age_seconds` and
resource identity. A correctly re-pinned config can tighten health age from30 to1
second while an existing API/worker client continues admitting5-second-old receipts
with its original30-second verifier. Neither refusal nor a policy update occurs.
Resource changes can likewise leave old client bindings, although the reproduced
case is specifically the freshness-policy change.

**Independent reproduction:**
`test_defect_config_tighter_freshness_is_not_applied_on_reload` constructs the actual
factory client at max-age30, swaps its loader to a new admitted config at max-age1
while retaining the installation/key, advances the deterministic clock5 seconds,
and gets `status=ready`; `client.health.max_age` is still30. The fixture replaces
file/calibration admission only, exercising the production reload comparison.

**Correction:** retain and compare the complete admitted config identity (including
resource and health policy), failing closed with restart-required on any change,
or atomically rebuild all client/health bindings from the new admitted config.
Do not treat matching installation/key as proof of unchanged readiness policy.

### Import-boundary observation — transitive driver imports remain

`execution_client.py:6` imports `execution_repository`, which imports
`execution_contract` → `frr_contract.py:10` → `emulation.autonomous_frr` →
`emulation.ospf`, `actions` and `runner`. A fresh interpreter importing just
`app.modules.autonomy.execution_client` confirms those modules enter `sys.modules`.
Thus the strict **no privileged driver imports** objective is not met, despite the
client having no `driver` or `run` method. No namespace attachment, subprocess
device command, privileged side effect or privilege escalation was observed on
import; this is a concrete layering/packaging observation, not another actuation
vulnerability. Move pure plan constants/contracts out of driver modules if that
import boundary is required. The import-only regression records current behavior.

### Checks that held, and exact recovery scope

- Wrong MAC, altered unsigned timestamp, valid-MAC foreign workspace, nonexpiring
  TTL and expired receipt replay are refused. Resetting TTL alone does not revive
  a receipt whose signed timestamp is already stale at the initial check.
- Valid recent receipts may be replayed inside their stated freshness window;
  process/iteration fields are authenticated but not tracked as a monotonic client
  watermark. No additional unbounded replay bypass was reproduced.
- Journal acceptance checks receiver health before staging and again afterward,
  and performs authority checks on both sides of staging. Independent tests prove
  initial health loss prevents stage, final health/authority loss raises, and the
  client never commits the caller's transaction. Scope/certificate/action authority
  still comes from `ExecutionAuthority`, not the receipt.
- `execution_repository.py:67–82` applies execution ID, resource, unreleased,
  lease and cancellation filters to the same claim query with `SKIP LOCKED`.
  Missing requested recovery work returns without a second/unfiltered query;
  recovery-only without an ID raises. The independent test inspects the actual
  compiled PostgreSQL statement and call count using an offline DB double.
- Receiver CLI `autonomous_frr_receiver.py:162–175` checks the exact target's
  resource/installation before persisting cancellation and passes that ID plus
  `recovery_only=True`. `execution.py:195–230` repeats filtered claiming, validates
  installation and forces `operation=recover`; its health publication branches
  at218 and252 are disabled for recovery-only. No concrete wrong-target fallback
  was found. Real transaction concurrency was not rerun.

### New-composition offline evidence

Independent file: `/tmp/opencode/adr023_client_review.py` —14 cases: three
defect-positive reproductions, ten safe-behavior cases, one import-boundary audit.
Combined gate: **262 passed in6.94s** (248 owner tests +14 independent checks).
Passing defect-positive tests confirms findings9–11; it is not acceptance.

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend:. \
  /home/DHB/.cache/pypoetry/virtualenvs/nanfo-backend-9hkWDLkY-py3.14/bin/python \
  -m pytest -q -c /dev/null -p no:cacheprovider --asyncio-mode=auto \
  -W ignore::DeprecationWarning \
  backend/tests/unit/test_execution_client.py \
  backend/tests/unit/test_autonomous_execution.py \
  backend/tests/unit/test_autonomous_frr.py \
  backend/tests/unit/test_autonomous_frr_startup.py \
  backend/tests/unit/test_autonomous_frr_final_checkpoint.py \
  backend/tests/unit/test_adr023_review_autonomy.py \
  backend/tests/unit/test_autonomy_service.py \
  /tmp/opencode/adr023_client_review.py \
  --basetemp=/tmp/opencode/adr023-client-review-gate
```

The owner's284 passes including36 PostgreSQL cases were read as attributed evidence,
not independently repeated here. Authentic calibration loading is not replaced in
production; synthetic loading seams in these tests cannot qualify an installation.
No application source was edited. Original1–8 closure and external live/physical
qualification boundaries below remain applicable.

## Final independent verification of finding8

Read the owner's625-test remediation report and independently traced both
configuration-mutation paths through the actual native transport:

- **Add:** `emulation/autonomous_frr.py:145–161` completes prepared-binding checks,
  full inventory, target inventory, argument construction and namespace ownership
  reads before calling `network.mutate(..., checkpoint)`.
- **Remove/compensate:** `emulation/autonomous_frr.py:192–208` completes the same
  preflight reads before passing the separately governed recovery checkpoint to
  `mutate`. Recovery remains independent of requester dispatch permission.
- **Native boundary:** `emulation/autonomous_namespace.py:55–68,73–77` performs
  PID/start-time/netns ownership validation, command validation, descriptor lookup
  and argv construction first. `final_checkpoint()` at66 is immediately followed
  by `subprocess.run` at67. **No driver/transport inventory, filesystem identity
  read or namespace sweep intervenes between the final callback and process I/O.**
  Post-command result handling and later verification reads do not reuse that check
  to authorize another mutation; each subsequent add/delete gets a new callback.

The independent `/tmp/opencode/adr023_frr_review_repros.py` now contains **12
safe-behavior tests**, replacing its historical vulnerability-positive assertion:

- Revocation during preflight: apply performs22 reads and compensation42 reads,
  the only final check sees revoked authority, and neither adds a write.
- Complete apply and compensation: all12 additions and all12 removals have an
  immediately preceding checkpoint, with no intervening inventory/ownership read.
- Actual `AttachedFRRNetwork.mutate`/`command` methods, with injected ownership and
  subprocess spies: PID/netns validation precedes the callback; success goes directly
  to pinned-descriptor process I/O. Revocation, certificate expiry and recovery-fence
  denial during the identity check prevent any subprocess invocation for add/delete.

**Final combined offline result:636 passed in8.26s** —598 owner regressions plus
38 independent safe-behavior cases (26 covering findings1–7 and12 covering finding8).
No vulnerability-positive assertion is included in this final gate. The command is
the combined command retained under “Historical first recheck commands and results”
below, with these additions/changes:

```text
add: backend/tests/unit/test_autonomous_frr_final_checkpoint.py
add: -W ignore::DeprecationWarning
use: --basetemp=/tmp/opencode/adr023-review-final-gate
```

Both independent files in that command now assert safe behavior. The extra owner
suite covers every final read, all12 add/delete boundaries, independent recovery,
partial-apply uncertainty and read-only preparation/verification. Existing dependency
deprecation warnings were filtered for this run. No dependencies were installed.

This closes the reproduced driver-ordering defect. It does **not** establish a
guaranteed observation-to-transition duration: subprocess execution and the complete
inventory/checkpoint/write path still require measured, independently qualified
timing. New receiver source fingerprints must be regenerated and reviewed before
installation. No real namespace mutation, live lab, PostgreSQL/Redis connection,
training, deployment or physical guarantee was exercised or conferred. Application
sources were not edited; only independent temporary tests and this report changed.

## Independent recheck disposition (supersedes original finding status)

Read the owner remediation results in `DistributedRealtime.md`,
`AutonomousExecution.md`, `IndependentValidation.md`, and `RetentionComplete.md`,
then inspected the current implementations and rewrote the independent reproductions
to assert safe behavior. Owner-reported infrastructure results below are attributed
evidence; this recheck ran only offline tests and fake device/transport boundaries.

| Finding | Independent disposition | Current decisive locations / evidence |
|---|---|---|
|1: permanent fanout poison cancels leadership|Resolved|`backend/app/events/fanout.py:50–106`: bounded quarantine+reset must confirm before completion; failed confirmation still cancels without ACK. Oversized hostname rejected. Independent tests check both paths and absence of raw hidden data in quarantine.|
|2: executable plan not independently bound|Resolved|`backend/app/modules/autonomy/safety_installation.py:10–37,45–75`: retained reviewed configuration binds canonical plans and physical mapping. Provider self-rehash cannot approve a changed plan/mapping. FRR descriptor trust is independently required; the omitted descriptor hash avoids the documented hash cycle.|
|3: qualified total delay widened|Resolved|`safety_installation.py:14–15,52`: actuation ≤ policy total ≤ reviewed total. Independent positive case accepts before the remaining window; evaluation at the certificate's exact exclusive expiry refuses.|
|4: Core observation reference pin bypass|Resolved|`backend/app/modules/autonomy/provider_state.py:27–39`: extraction covers both persisted JSON bodies, including evidence strings, before Core insert. Independent tests prove all pins precede insert and an owner-scope refusal prevents insert.|
|5: receiver final row-lock authorization gap|Resolved|`backend/app/modules/autonomy/execution.py:45–62,80–107,127–163`: fresh post-lock/flush checks. The independent checkpoint test observes `[allowed, revoked]`, raises the revocation error, and never commits. The separately identified driver-level finding8 is also resolved.|
|6: incoming duplicate bytes fan out|Resolved|`backend/app/modules/telemetry/replay.py:21–60`, `backend/app/events/consumers/telemetry_consumer.py:153–161`: exact active replay rebuilt from stored fields; scope/value/provenance/correlation conflicts refused; tombstones suppress lookup and delivery. Unknown incoming envelope/payload fields containing `foreign-secret` are discarded, not exposed to detection or fanout.|
|7: archive ancestor substitution|Resolved|`backend/app/modules/telemetry/archive.py:57–88,95–116`: descriptor walk and chain identity checks, same-descriptor readback, post-I/O path validation. Six independent service-level combinations (symlink/directory × before/link/readback) raise before `archive_and_delete`; unchanged-store restart reads exact bytes.|
|8: FRR inventory after final authority check|Resolved|`emulation/autonomous_frr.py:145–161,192–208`; `emulation/autonomous_namespace.py:55–77`: preflight and native PID/netns reads precede the final checkpoint, immediately followed by process I/O. Independent denial and successful-ordering checks pass for both add and delete.|

**No new concrete defect was reproduced in archive deletion or canonical event
replay during this recheck.** Tests exercise the actual retention service and store
with a deletion spy, and actual persistence/replay/consumer code with owning
repository doubles. They do not execute database deletion or claim cross-store
atomicity under arbitrary privileged filesystem mutation.

### Finding8 — resolved; historical defect and owner remediation

**Independent closure:** verified by the final636-test gate above. The original
defect description and owner response below are retained as historical evidence;
pre-fix line numbers and vulnerability-positive results are not current behavior.

**Owner remediation for reviewer verification (2026-09-20): implemented.**
All per-add and per-delete binding/inventory reads now precede the final callback.
`AttachedFRRNetwork.mutate()` places that callback inside the native transport,
after its PID/start-time/netns descriptor validation and immediately before
`subprocess.run`; there is no post-check inventory or namespace sweep. Every add
uses current receiver dispatch authority; every delete uses the separately governed
recovery ownership/fence callback. Prepare is read-only; verification performs
configuration readback and reachability probes but no route/rule writes.

Offline verification: **625 passed**, including the26 reviewer safe-behavior cases
and `/tmp/opencode/adr023_frr_review_safe.py`, a separately named safe assertion of
the supplied new FRR repro. Original defect repro was preserved and rerun: it now
fails its `[True,False]` assertion because the only check sees `[False]`; the safe
adaptation confirms22 reads and **zero writes**. This is owner-run verification,
not a claim that the independent reviewer has signed off on the new source.

New driver tests exercise revocation and deterministic deadline expiry at each of
the22 final reads, every one of12 add/delete boundaries, loss of recovery authority
at each of42 pre-first-delete reads, final namespace binding reads, partial mutation
followed by independently authorized recovery, and denied recovery retaining
uncertainty with no cleanup writes. Native transport tests mock the subprocess and
prove namespace validation precedes the final callback with nothing read afterward.
No namespace command, live lab, PostgreSQL/Redis service, training or commit ran.
Scoped Ruff and whitespace checks pass. Receiver locks/authority ordering remains
the previously reviewed implementation. Source pins must be regenerated and reviewed
for these driver/transport changes; no installed evidence was rewritten.

Aggregate timing remains an installation obligation: the driver retains22 device
reads before each of12 additions (plus preparation/readback), not a claim that it
finishes in a short calibrated actuation duration. Slow reads consume the same
observation-to-transition budget and the final checkpoint rejects expired work
before its next write. No delay threshold was increased. Parent acceptance must
measure/qualify the complete path, including all reads/checkpoints/writes/transition;
five-second individual command timeouts are not a guaranteed aggregate bound.

**Exact location:** `emulation/autonomous_frr.py:149–156`, especially the checkpoint
at151 followed by `read_owned()` at153 and `inventory()` at154 before the write at156.
Related bounded-I/O implementation: `emulation/autonomous_namespace.py:55–65`.

Each route/rule mutation gets a checkpoint, but that checkpoint is followed by a
full reserved-table inspection: five routers × two tables × two native read commands,
then another two commands for the target inventory. These **22 synchronous device
reads occur after the final server authorization/deadline check**. Individual
namespace commands have a five-second timeout; this is a substantial wait window,
not merely the unavoidable instruction gap immediately preceding I/O. The driver
does not recheck the certificate, STOP, actor authority or resource exclusion after
those reads. Namespace ownership checks cannot establish current server authority.

**Offline reproduction:**
`/tmp/opencode/adr023_frr_review_repros.py::test_frr_applies_first_mutation_after_authority_revoked_during_inventory`.
Prepare an action1 plan against the existing fake kernel, let the first checkpoint
pass, and revoke authority on the first subsequent inventory command. The real
`LinuxFRRDriver.apply()` performs all22 reads and then one `ip route add`. Only the
checkpoint for the following operation detects revocation. Assertions confirm
checks `[True, False]` and **one unauthorized mutation**. No real namespace command
or clock waiting was used. Certificate expiry during the same reads follows the
same missing-check path; it is not a separate executed timing test.

**Impact:** in an admitted native FRR installation, STOP/revocation or certificate
expiry during inventory does not prevent the next mutation. Subsequent rejection
and compensating recovery cannot undo the fact that dispatch occurred outside its
authorization window. This is introduced by the new FRR path; it does not reopen
the repaired journal row-lock ordering in finding5.

**Required correction:** retain the foreign-resource inventory checks, then perform
a fresh receiver authority/exclusion checkpoint and namespace-ownership check after
the last potentially blocking read, immediately before every add. Apply equivalent
final ownership/exclusion ordering to compensation (without requiring requester
authority). Keep failures uncertain until exact compensation verifies. Add a
driver-level regression where inventory changes authority/deadline; require zero
new writes. Review aggregate read budgets against the installed actuation duration.

### Historical first recheck commands and results

The following505-test result predates the finding8 fix. The final result above
supersedes its status and the two temporary test files now assert safe behavior.

Safe-behavior suite: `/tmp/opencode/adr023_review_repros.py` — **26 passed**.
New FRR finding: `/tmp/opencode/adr023_frr_review_repros.py` — **1 passed**, explicitly
asserting the remaining defective behavior, not implementation acceptance.

Combined current owner+independent offline gate: **505 passed in10.68s** (478 owner
tests,26 safe-behavior tests,1 new defect reproduction). Use the existing backend
Poetry interpreter, from repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend:. \
  /home/DHB/.cache/pypoetry/virtualenvs/nanfo-backend-9hkWDLkY-py3.14/bin/python \
  -m pytest -q -c /dev/null -p no:cacheprovider --asyncio-mode=auto \
  backend/tests/unit/test_adr023_review_autonomy.py \
  backend/tests/unit/test_autonomous_execution.py \
  backend/tests/unit/test_autonomous_frr.py \
  backend/tests/unit/test_autonomous_frr_startup.py \
  backend/tests/unit/test_autonomous_causal.py \
  backend/tests/unit/test_autonomy_safety.py \
  backend/tests/unit/test_independent_validation.py \
  backend/tests/unit/test_retention_complete.py \
  backend/tests/unit/test_telemetry_lifecycle.py \
  backend/tests/unit/test_telemetry_replay.py \
  backend/tests/unit/test_telemetry_consumer.py \
  backend/tests/unit/test_telemetry_persistence.py \
  backend/tests/unit/test_fanout_quarantine.py \
  backend/tests/unit/test_distributed_realtime.py \
  backend/tests/unit/test_fleet.py \
  backend/tests/unit/test_spatial_geometry.py \
  /tmp/opencode/adr023_review_repros.py \
  /tmp/opencode/adr023_frr_review_repros.py \
  --basetemp=/tmp/opencode/adr023-review-recheck-gate
```

The initial combined invocation with `/usr/bin/python` produced501 passes and4
dependency failures (`reportlab`/`asyncpg` absent). The existing Poetry environment
resolved those failures with no source changes or installs. The failures occurred
at imports/session construction; no infrastructure was contacted. The successful
run reports existing Python3.14 dependency deprecation warnings. No repository
bytecode, coverage or pytest cache was requested.

### Remaining external evidence, distinct from resolved software findings

- Owners report349 scoped Autonomy passes including32 disposable PostgreSQL cases
  (ten lock/revocation/expiry races),175 realtime checks including real sockets,
  and77 retention checks including PostgreSQL substitution/deletion/restore cases.
  Those results were read, not independently rerun here.
- Native FRR deployment still needs the documented exclusive namespace handoff,
  matching frozen model/runtime source and image or separately qualified model,
  compatible native instrumentation, complete causal attribution, preregistered
  transition measurements, reviewed guarantees/runtime-equivalence pins and aligned
  fresh observations. No checked-in synthetic fixture satisfies those prerequisites.
- Source-matched live accept→dispatch→readback→STOP/revocation→recovery remains an
  external acceptance gate once the required evidence and reviewed updated source
  fingerprints exist; all eight reproduced software findings are now resolved.
  No physical calibration, production safety or live infrastructure was certified
  by this recheck. Application sources were not edited.

## Historical first-pass review and owner responses

The original findings and line numbers below describe the pre-remediation source.
Their vulnerability-positive test names are historical: the same temporary repro
file now contains the safe-behavior assertions documented above.

### Execution-owner response: findings2/3/4/5

Remediation implemented with349 passing scoped tests (32 actual PostgreSQL cases),
including independently reviewed executable/physical mapping bindings, bounded total
delay, exact Core evidence pinning and post-lock authorization/expiry revalidation.
Ten real execution/history-row lock races use committed Identity role removal or
certificate expiry and prove no simulated device-boundary success. Full scope,
commands, remaining deployment blockers and reproduction interpretation are recorded
at the top of `AutonomousExecution.md`; independent schema handoff is in
`IndependentValidation.md`. Original findings/reproductions below are retained.
This response does not claim closure of other reviewers' findings or live calibration.

Reviewed the current working tree against ADR-023, the code-review skill, repository
guardrails and owning contracts. Application sources were not edited. All executions
were offline; no Docker, lab, database, Redis or shared-service mutations were used.

## Ranked findings

### 1. P1 — An API-valid oversized event repeatedly cancels distributed leadership

**Locations:** `backend/app/events/fanout.py:39–58`, especially `46–47` and
`56–58`; `backend/app/modules/network/schemas.py:64–68`.

`FanoutPublisher.publish()` converts *all* exceptions, including deterministic
schema/size rejection, into `CancelledError`. `process_entry()` only catches
`Exception` (`backend/app/events/bus.py:83–110`), so such an event never gets a
completion marker, ACK or dead-letter receipt. The supervised consumer cancellation
tears down leader work (`backend/app/events/distributed_realtime.py:95–108`). The
same pending event cancels the next leader when reclaimed.

This is reachable through ordinary authorized inventory creation: `hostname` has
no length limit, its database column is `Text`, and `DeviceService.add_device()`
puts it into the durable event (`backend/app/modules/network/service.py:234–249`).
A 300,000-character hostname exceeds the default 262,144-byte fanout limit while
passing the request model. One tenant's inventory event can therefore repeatedly
interrupt domain processing/collection and invalidate other tenants' sockets.

**Reproduction:**
`test_api_valid_oversized_device_event_cancels_instead_of_deadletter` creates that
request, runs the actual WS translator/publisher through `process_entry()` twice,
and observes `CancelledError` both times with zero ACKs, DLQ appends or completion
markers. Redis is an injected offline transport double; no Redis failure is needed.

**Required correction:** distinguish permanent invalid/oversized payload failures
from lease/transport failure. Reject oversized inventory before durable acceptance
and give already-persisted poison entries a bounded terminal/reconciliation path.
Preserve cancellation semantics for genuinely unpublished transient work.

### 2. P1 — Independent calibration validation does not bind the executable plan

**Location:** `backend/app/modules/autonomy/safety_installation.py:27–39`.

The validator compares action IDs, logical demand/egress mappings and queue bounds,
but never examines `InstalledAction.plan`. The independent configuration schema
has no executable plan or physical mapping binding either
(`backend/app/modules/autonomy/calibration_verification_models.py:51–55`). A
provider installation can therefore describe qualified logical route B while
carrying an unrelated, schema-valid lab switch path.

The receiver compares the command plan only to this same installed plan
(`backend/app/modules/autonomy/execution.py:48–53`); staging copies it directly
(`backend/app/modules/autonomy/execution_repository.py:53–58`). Readback verifies
the installed executable plan, so it does not detect disagreement with the logical
route whose safety inequalities were evaluated.

**Reproduction:**
`test_independent_validator_accepts_unqualified_executable_plan` changes only
`actions[0].plan.paths` from `s1 → s3 → s2` to `s1 → s4 → s2`. The production
independent validator still returns the supplied installation digest. Logical
routes, calibration and independent campaign configuration remain identical.

**Precondition/impact:** requires an operator-installed provider document, not an
unauthenticated request. A mistaken or substituted plan is nevertheless promoted
as independently validated even though the certificate proves a different action.

**Required correction:** bind a canonical executable plan and physical
demand/port/egress mapping into the reviewed configuration, then independently
check that binding at installation and receiver dispatch. Merely pinning the new
provider document's hash does not establish equivalence to the qualified action.

### 3. P1 — Provider policy can exceed the campaign's qualified total delay

**Location:** `backend/app/modules/autonomy/safety_installation.py:17–25`.

`config.max_delay_seconds` is tested as the complete observation-to-transition
delay (`backend/app/modules/autonomy/calibration_verification.py:55–67`). The
installation adapter instead compares it with only
`data.actuation_delay_upper_seconds`; it never constrains
`data.policy.max_delay_seconds`. The shield uses the latter to determine the
remaining dispatch allowance (`backend/app/modules/autonomy/safety.py:412–425`).

Consequently a profile qualified for a 0.1-second total delay can install a
10-second policy allowance and issue a valid certificate 0.5 seconds after its
observation (subject to the separate one-second horizon). Receiver reevaluation
uses that same unchecked policy and cannot restore the campaign's tighter limit.

**Reproduction:**
`test_independent_validator_accepts_delay_outside_campaign` builds the actual
typed installation/configuration, sets `policy.max_delay_seconds=10.0`, and checks
that independent validation accepts it. `CalibratedSafetyProvider.evaluate()` at
`observed_at + 0.5` returns `admissible=True` with a future expiry, despite
`loaded.configuration.max_delay_seconds == 0.1`.

**Required correction:** explicitly distinguish total qualified delay from the
remaining actuation duration. Bound the runtime policy's total delay by the
reviewed campaign maximum and derive the exclusive dispatch deadline from it.
Reject a provider profile that silently widens that envelope.

### 4. P1 — Core observation inserts bypass pinning for evidence-string references

**Location:** `backend/app/modules/autonomy/provider_state.py:29–40`.

`record_observation()` pins only `observation.samples`, then writes the entire
observation with a SQLAlchemy Core `insert`. Core inserts do not invoke the ORM
`before_flush` guard registered for `AutonomousObservation`
(`backend/app/modules/autonomy/service.py:58–63`,
`backend/app/modules/telemetry/references.py:129–144`).

The persisted `Observation.evidence` also accepts the explicitly recognized
`telemetry_record:<UUID>` reference syntax. Such references get no Telemetry scope
check or pin through this path. A frame with `samples=[]` can durably retain a
foreign-workspace record reference, or retain an unpinned same-workspace reference
that subsequent archival deletes from active history. Completed historical
reconciliation does not revisit newly inserted frames.

**Reproduction:**
`test_core_observation_insert_bypasses_evidence_reference_pins` supplies an otherwise
valid measured observation with no samples and one `telemetry_record:` evidence
string. The real method emits the Core insert, the normal reference extractor
finds the stored UUID, and the Telemetry pin method is never called.

**Required correction:** extract and pin all recognized references from the exact
persisted observation and safety frame before the Core insert, in the same
transaction, or use the existing guarded ORM path. Foreign references must fail
the existing Telemetry workspace/network check. This finding is durable-reference
integrity/retention failure; it does not demonstrate reading another tenant's bytes.

### 5. P2 — Receiver authority becomes stale across the final execution-row lock wait

**Location:** `backend/app/modules/autonomy/execution.py:45–57`.

`checkpoint()` calls `authority.check()` **before**
`ExecutionRepository.owned()`, which acquires an execution-row `FOR UPDATE` lock
and performs additional queries (`execution_repository.py:77–88`). After that
potentially blocking operation, the receiver commits and returns permission to
mutate without rechecking actor authority or approval/certificate expiry.

The final clock check in `ExecutionAuthority.check()` (`execution_authority.py:86–89`)
therefore precedes the final possible wait. An independent transaction can hold
the execution row, allow membership revocation or expiry while the receiver waits,
and then release it. An unchanged cancellation flag and valid execution lease let
the checkpoint succeed. The driver's next operation is the actual device write.

**Reproduction:**
`test_receiver_does_not_recheck_revocation_after_execution_row_wait` injects a
contended owning-repository call that yields and changes current authority to
revoked. The actual `ReceiverJournal.checkpoint(mutation=True)` still returns
success; its only authority check saw the old value. This is an offline ordering
reproduction, not a claim of having run a PostgreSQL contention campaign.

**Required correction:** acquire all potentially contended owner locks before a
fresh final authority/deadline check, retaining the established control-first lock
order. Add an actual two-session race regression when disposable PostgreSQL
testing is admitted. Apply the same ordering review to begin-apply and finish.

### 6. P2 — Duplicate/tombstoned telemetry replays fan out unvalidated event bytes

**Locations:** `backend/app/events/consumers/telemetry_consumer.py:146–154` and
`backend/app/modules/telemetry/service.py:947–954`.

Persistence returns `False` for a matching event ID or tombstone **before** parsing
or comparing the payload. The newly added replay branch interprets every `False`
as “committed before fanout” and publishes the incoming payload. A replay with the
same event ID but a different workspace/network/value can therefore produce a
tenant-routed metric that was never persisted. Even an exact replay of archived
telemetry gets reintroduced into realtime despite being intentionally tombstoned.

Measured-alert ingestion rereads its owning record, but `_push_telemetry_delta()`
does not. Subscriber authority checks authorize the replay's routing scope; they
do not establish consistency with the original durable event.

**Reproduction:**
`test_duplicate_event_fanout_uses_unpersisted_changed_payload` makes the owning
repository return an existing event in workspace A with value 1, then invokes the
real persistence/consumer code with workspace B and value 999. Fanout receives B
and 999. Requires an internal conflicting replay and a missing/expired completion
marker, not direct unauthenticated HTTP access.

**Required correction:** distinguish inserted, exact-active-replay, archived and
conflicting-event outcomes. Recover fanout from immutable persisted bytes or a
durable owning receipt; reject conflicting replays and suppress archived ones.

### 7. P2 — Archive reopens its root through symlink-swappable ancestors

**Remediation outcome (2026-09-20): fixed; scoped verification passed.**
`TelemetryArchiveStore` now opens `/` and every subsequent component using
descriptor-relative `O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC`. Admission records each
component's device/inode identity. Reads/writes recheck that chain, retain the
opened descriptors through I/O, and rewalk/check the configured path before
returning success. Publication and checksum readback use the **same archive root
descriptor**. A symlink or ordinary-directory substitution is refused even if the
replacement contains identical bytes. Runtime permission changes are also refused.

Root policy is current-UID ownership and exact0700; archive files must be owned
regular files with0400 or0600 mode. Ancestors must be owned by root/current UID
and not group/world writable, except trusted sticky directories such as `/tmp`.
No persistent open descriptor is needed across store lifetimes: reopening the
unchanged legitimate directory preserves receipt-backed reads and restore.

Verification: **77 passed** across retention PostgreSQL, telemetry lifecycle
PostgreSQL and their unit suites, on newly created disposable
`nanfo-retention-review7-pg`. Twelve new actual-PostgreSQL combinations cover
ancestor/root × symlink/directory × before-publication/during-publication/readback.
Each checks that archive/delete is never called, even a post-error commit leaves
the telemetry row and no receipt/tombstone, and repairing the original path plus
restarting permits actual deletion and restore. Unit regressions additionally
cover substitution during reads, same-byte impostor directories and permission
changes. Scoped Ruff and whitespace checks passed.
The disposable container was stopped and auto-removed after verification; no
shared PostgreSQL/Redis services or data were modified.

The original `/tmp/opencode/adr023_review_repros.py` archive reproduction passed
before remediation and now fails at `store.write` with `NotADirectoryError`, before
writing into the substituted tree. That reproduction asserts the vulnerability;
its expected failure is distinct from the passing regression gates above.
No telemetry service/consumer, parent composition or other reviewer findings were
modified for this correction. Finding6 remains assigned to the distributed agent.
The original review evidence below is retained for traceability; this scoped
outcome does not supersede the review's overall recommendation for other findings.

**Location:** `backend/app/modules/telemetry/archive.py:41–47`.

Construction checks `root.resolve() == root`, but subsequent reads/writes use
`os.open(self.root, ... O_NOFOLLOW)`. `O_NOFOLLOW` protects only the final path
component. Replacing an ancestor with a symlink after construction redirects the
store into a different directory; the runtime check only tests the final
directory's owner and mode.

**Reproduction:**
`test_archive_follows_replaced_ancestor_after_admission` constructs a store under
`operator-path/archive`, renames `operator-path`, replaces it with a symlink to
`alternate`, and writes a record. Write/readback succeeds, but bytes land in
`alternate/archive`; the original archive remains empty.

**Precondition/impact:** requires ability to replace an ancestor (for example a
mutable deployment path); this is not a demonstrated privilege escalation against
a protected fixed tree. After successful readback the retention service may commit
the SQL delete (`retention.py:74–77`), leaving the supposed archive on an unintended
filesystem or outside the configured backup location.

**Required correction:** open every ancestor with descriptor-relative
`O_DIRECTORY|O_NOFOLLOW`, as Network's asset store does, and enforce/pin the intended
directory identity across publication and readback. Reject redirection before SQL
deletion is possible.

## Verification and review boundaries

Independent reproductions: `/tmp/opencode/adr023_review_repros.py`. These tests
assert the observed defective behavior; their passing is confirmation of a defect,
not acceptance of the implementation. Fixtures are synthetic and confer no safety
qualification. Transport/database doubles isolate ordering and emitted payloads.

From repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend:. python -m pytest -q \
  -c /dev/null -p no:cacheprovider --asyncio-mode=auto \
  backend/tests/unit/test_autonomous_execution.py \
  backend/tests/unit/test_retention_complete.py \
  backend/tests/unit/test_fleet.py \
  backend/tests/unit/test_distributed_realtime.py \
  backend/tests/unit/test_spatial_geometry.py \
  backend/tests/unit/test_independent_validation.py \
  /tmp/opencode/adr023_review_repros.py \
  --basetemp=/tmp/opencode/adr023-review-unitdata
```

Result: **211 passed in 3.97s**, including all seven independent reproductions.
No coverage/cache/bytecode files were requested in the repository.

Inspected canonical geometry/transforms and RF adaptation, distributed fanout and
consumer replay, cross-owner reference guards, archive/dedup/restore, fleet
leases/spool/authorization, live model registry/qualification/inference, independent
calibration and receiver recovery. No additional concrete defect is asserted for
geometry, fleet or the live model's benchmark rehash path. Existing unit passes do
not settle database races or physical receiver behavior; those were not executed.

The only repository file created by this review is this report. Findings refer to
the working-tree source examined during review; the parent should recheck locations
if concurrent implementation changes land before remediation.

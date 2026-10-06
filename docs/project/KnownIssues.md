# Known Issues

## ADR-028 remediation — 24 September 2026

Source: [ADR-028](../adr/ADR-028-full-stack-review-remediation.md) §6–§8. The implementation
is delivered, but these limits remain. Owner-only steps are listed once, in ADR-028 §8.

| Open issue / impact | Current boundary and next action | Owner role |
|---|---|---|
| `noUncheckedIndexedAccess` not enabled | Enabling it gives about 388 TypeScript findings (≈206 in platform code, ≈150 in Twin tests; Twin production files already pass). `exactOptionalPropertyTypes`, `noImplicitReturns` and `allowUnreachableCode: false` are on. Fix the findings in bounded batches, then enable the flag in `tsconfig.app.json`/`tsconfig.test.json`. | Frontend owners |
| No rotation command for the receiver-health keypair (C21) | `deploy/manage.py init` generates the Ed25519 keypair once. The private key lives in `${NANFO_STATE_DIR}/receiver/`, which no container mounts, and is installed manually on the FRR receiver. Rotation means a manual regenerate, restage and reinstall. Add a `rotate --secret receiver_health` path with overlap for in-flight receipts. | Deployment owner |
| Docker image, browser and live-lab lanes not executed locally | The integrator ran the `docker compose config` render tests (9 + 6 passed, ADR-028 "Final verification"). Image builds, trivy (`packaging`), `production-browser` and any lab build or run remain unexecuted locally; their first CI run (or the owner's lab qualification, §8.5) is the evidence. | Integration / CI owners |
| `@types/three` 0.185.4 while `three` is `^0.170.0` | Pinned explicitly after removing `@react-three/drei`, which dropped the transitive types. Typecheck passes, but the types describe a newer API than the runtime. Align to a 0.170-compatible `@types/three` and re-run typecheck. | Frontend owners |
| Five host-only tools ship inside the backend image | `accept_continuous_feed.py`, `audit_isolated_suite.py`, `audit_experimental_lab.py`, `prepare_strathmore_demo.py` and `release_manifest.py` import modules the image context excludes. They fail if run inside the image and are harmless outside it. Move them out of the image context or document host-only use in each. | Deployment / tool owners |
| Historical ADR024 re-verification needs the preserved runner copies | ADR-028 edited `scripts/adr024_campaign.py` and `scripts/recover_qualified_runtime.py`, so they are successors whose hashes no longer match the pinned ADR024 plan, and they correctly refuse historical plans. Re-verify with the preserved runner copies in the private store or from git `e55a4f5`. | Research owner |
| `NETWORK_ASSET_*` are read from the process environment only | `AssetSettings` does not read `backend/.env`, and `backend/.env` forbids unknown keys, so a `NETWORK_ASSET_*` line there makes the app fail at startup. Set them in Compose or the environment (`backend/.env.example` documents them as prose). | Deployment / Network owners |
| Campaign-014 keeps 10 tracked private-evidence files | Resolved for CI by the owner-approved exception (ADR-028 §7.2, `security/evidence-location-exceptions.v1.json`): exact path, rule and SHA-256 per file; the full scan reports 0 findings. The files stay in git history; a history rewrite remains an owner option (§8.4). | Owner |
| Bundle cap raised to 450,000 B without owner confirmation | `perf:bundle` passes at 422.34 KiB only under the raised cap (ADR-028 §7.3). A veto means trimming ADR-028 UI or restoring 420,000 B. | Owner / frontend |
| Successor runtimes unqualified | The successor lab image, the receiver successor wrapper (policy v2) and the FRR runtime bindings (invalidated by `RECEIVER_SOURCES` edits) are checked offline only. No result claim is valid until fresh qualification (ADR-028 §8.5). No confidence calibration exists for the real model, so autonomous dispatch stays C17-gated. | Owner / research |
| Pre-ADR-028 deployments refused | `manage.py` refuses ADR-020–027 installations until a reviewed upgrade procedure exists (ADR-028 §8.8). Fresh installs are unaffected. | Deployment owner / owner |
| DSN-gated suites: first remote run still pending | Executed locally by the integrator on throwaway PostgreSQL 17.11 / Redis 7.4.11: migrations round trip clean, 323 database-contract cases and 29 stream-retention cases passed with zero skips; the run found and fixed two product defects (ADR-028 "Final verification"). `COVERAGE_FLOOR` is 84 (85.60 % measured). Remote CI has not run these jobs yet. | Integration / CI owners |
| Bounded residuals in delivered fixes | 1. A login that completes at the same moment as `revoke_user_sessions` can create one new session; deactivation still denies it, but a password change or role downgrade can leave it usable until it expires. 2. The C26 report quota counts only the organisation's active workspaces; deleted-workspace reports fall under the global reserve only. 3. Event order is kept per entity within a page, not across failure rounds, so consumers keep their C13 sequence/revision checks. 4. Telemetry rows stranded by earlier re-registrations are released only by a clean reconciliation. 5. The WebSocket `?token=` compatibility path remains for one release. 6. `autonomous_executions` has the same insert-order hazard the report outbox had under its new foreign key if both rows are ever added in one ORM flush; production inserts the resource row first with SQL, so it is harmless today. | Identity / Report / Platform / Telemetry / Autonomy owners |

## ADR027 register — 21 September 2026 (still open unless noted)

Authority: [seven-item review matrix](ReviewClosure-Completion.md). Scope-limited
passes below do not close the open issues in this register.

| Open issue / impact | Current boundary and next action | Owner role |
|---|---|---|
| Historical receiver credential exposure |71 exact-byte private copies verified; active files removed, but index/history exposure remains. Confirm non-reuse/invalidation and investigate copies/access before explicitly authorized history remediation. [Evidence](ReviewClosure-Evidence.md). ADR-028: full-history gitleaks now allows exactly these 71 tokens; the history rewrite remains an owner action (ADR-028 §8.4). | Operator / repository administrator |
| Dependency residuals and incomplete image coverage | npm0. ADR-028 removed the ecdsa exception (python-jose is gone) and split the emulation audit into `emulation` (hash-pinned successor lock, 0 advisories) and `emulation-frozen`. The remaining frozen Torch/emulation exceptions now expire between **2026-10-29 and 2026-11-26**; the `ai` coverage gap expires **2026-12-03**. Exact CPU-wheel audit gap remains. Apply the versioned successor plan and source-matched requalification; exceptions are not fixes. Image/OS SBOM remains open (CI trivy scans are prepared, not yet run remotely). [Dependencies](ReviewClosure-Dependencies.md). | Security / runtime owners |
| Remote CI and historical-evidence lane | Local full-stack5/5, retention27 and repaired nginx header/proxy24 passed; remote workflow execution/required branch checks remain unverified. Clean upgraded PG254pass/12skip plus exact Redis12pass covers all266 selected cases after dev-only fakeredis Lua/lupa repair and clean-CI EVAL checks. Provision protected checksum-verified historical artifacts separately from public CI. ADR-028 prepared the workflows, skip budget and a 13-check ruleset; applying them is an owner action (ADR-028 §8.3). | Integration / CI owners |
| Retention adoption and saturation | ADR027 left operator-only archive-before-delete off by default. ADR-028: the supervised deployment now runs the `stream-retention` (DLQ included) and `telemetry-retention` loops as core services, and producers refuse new events at 0.90 of Redis `maxmemory`. Still open: audit group history, capacity monitoring of memory/disk/lag with protected backup, and representative load evidence. Pending/unread entries and archives can still grow, and there is no global disk admission. [Streams](ReviewClosure-Streams.md). | Operations |
| Experimental joined acceptance and exhausted operational domain |017 **FAILED**:4/4 smokes,67/68 matrix completed/1 invalid (`path1-1564-qualified`, `protected_regular_owner_file_required`); all20 fault outcomes completed. Independent018 accepted the protected-read repair and reconfirmed failure; exact live interleaving remains unproven. Frozen gates115backend/3historical skips,34receiver,2STOP passed. Count-only1342 false reservation corrected in active extractor with60 passing tests. **996/1000 genuine/preregistered reservations,4 available/36 required,deficit32** still blocks fresh plan. Preserve genuine reservations/split; no018 plan/admission/launch or experiment completion. [Experimental](ReviewClosure-Experimental.md). | Experimental owner / protocol reviewer / parent |
| Broader recovery qualification and release identity | Latest **c8rorfzd core0029 accepted28pass/0fail/5blocked**, backend `a2bf67af…`/source `f7105617…`. Subsequently only verifier seed scanner/test source changed (`9e46d086…` verifier); core behavior unchanged, entire tree not byte-identical. Distributed failover, lab binding/congestion, model diagnosis and measured-telemetry survival remain blocked. New public refresh/retention receipts and separate private backup/key/result copies ready; off-host escrow, whole-host/load acceptance and explicit0027/0028 upgrade rehearsal remain. [Deployment](ReviewClosure-Deployment.md), [bundle](ReviewClosureEvidence/README.md). | Deployment / operations |
| Research and physical claims | Physical RF survey/equipment unavailable; no intended-user study or independent repeated training supplied. Proactive timing/workload/stability ablation and complete recovery need evidence. Dense-scene real-GPU/enterprise performance is unestablished. [Research](ReviewClosure-Research.md). | Student / research / site operators |
| Historical malformed audit rows | Future production repaired under ADR026; existing wrong/unscoped rows require separately reviewed append-only correction, preserving original evidence. | Identity / data owner |

## Resolved at the recorded scope

- Asset binary-header restore mismatch, paged metadata, opaque request identity,
  generated-secret/loopback setup, exact proxy attribution and route recovery have
  delivered regressions. Final browser-fixture suite **70/70, no retries** and real
  production full-stack **5/5** passed; these are separate lanes.
- Clean upgraded PostgreSQL now records **254 passed/12 skipped** and the separate
  real-Redis subset **12 passed/0 skipped**, covering all266 selected cases. The
  development Lua dependency defect and old nginx include fixture failure are
  repaired; nginx/proxy **24 passed/0 skipped**. The earlier full backend checkpoint
  still reports317 skips; these targeted checks do not erase its skips or rerun it.
- Historical0027 distributed acceptance and ADR024 qualifiedv4 recommendations
  remain valid only for their recorded scope. Neither is current0029 distributed
  acceptance or calibrated production autonomy.
- Final portable gate **441 JUnit cases/zero skips/11 explicit deselections** and
  original AI **463 passed** reaffirm local software scope, not remote CI or research closure.

## Usage
Track active defects with impact, scope, workaround, and owner.

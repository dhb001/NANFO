# ADR027 R07 — dependency security and portable CI

Review date: **2026-09-21**. Security plan/policy version: **1**.
Status: upgrades and fail-closed gates implemented; reviewed residual risks remain.
Remote GitHub execution and final source-frozen full-stack acceptance remain parent
integration work. This report does not qualify a new emulation image or model.

## Exact lock changes

| Scope | Before | After |
| --- | --- | --- |
| Backend FastAPI | 0.115.14 | 0.135.4 (`~0.135.4` compatible minor line) |
| Backend Starlette | 0.46.2 | 1.6.0 |
| Backend pytest | 8.4.2 | 9.1.1 |
| Backend pytest-asyncio | 0.24.0 | 1.4.0 (pytest9 compatibility) |
| Backend development pypdf | 6.8.0 | 6.19.0 |
| Backend new FastAPI dependency | absent | annotated-doc0.0.5 |
| Frontend react-router / react-router-dom | 6.30.4 | 7.18.4 |
| Frontend Vitest and all seven @vitest packages | 3.2.7 | 4.1.11 |
| Frontend development js-yaml | 4.3.1 | 4.3.2 |
| AI **development only** pytest | 8.4.2 | 9.1.1 |

Vitest transitive upgrades: chai5.3.3→6.2.2, es-module-lexer1.7.0→2.3.2,
std-env3.10.0→4.2.0, tinyexec0.3.2→1.3.1, tinyrainbow2.0.0→3.1.1.
New frontend transitives: @standard-schema/spec1.1.0, cookie1.1.1, obug2.2.1,
set-cookie-parser2.7.2. Obsolete Remix router/Vitest3 transitives are removed.
React18, Three, Vite6 and application contracts retain their versions.

Compatibility edits: remove already-enabled v7 future flags from `src/main.tsx`,
explicitly include Node types in `tsconfig.app.json` for Vitest4, exclude the new
separate Playwright full-stack suite from Vitest discovery. No frontend view or
backend application source was edited by this owner. FastAPI0.141.1 was evaluated
then rejected because its lazy `_IncludedRouter` representation breaks the current
readiness contract test; the audited0.135.4 line preserves compatibility.

The AI lock comparison proves only the pytest package and project dev metadata
changed. CPU Torch2.8.0+cpu, runtime/transitive wheels, source and model weights were
not changed. No installation ran in `ai-engine/.venv`. AI tests used
`/tmp/opencode/r07-ai`; backend tests used `/tmp/opencode/r07-backend` (Python3.12.14).
A Poetry invocation unexpectedly selected the shared backend environment despite
`VIRTUAL_ENV`; its five prior versions and removed lupa2.8 were immediately restored,
and the newly installed annotated-doc removed. Parent was notified. Subsequent
installation/testing used explicit temporary interpreter paths.

## Reproducible audit gate and exact residuals

`.github/workflows/dependency-security.yml` runs on every PR, main/master push,
weekly Monday schedule and manual dispatch. Python inventories read **every locked
runtime and development package**, including platform-specific pins, without
installing the target environments. Frozen emulation requirements are queried with
`--no-deps --disable-pip`: this is a complete listed-pin audit, not a claim to cover
unlisted image/OS/build packages. pip-audit is pinned2.10.0; npm audits the checked
lock, production and development, failing all severities. Feed/tool/JSON errors,
missing inventory entries, new IDs, changed versions, missing review metadata,
expired exceptions and unknown skips fail. There is no blanket package ignore,
severity exemption, `continue-on-error`, or `|| true` in the audit gates.

```sh
uv tool run --from pip-audit==2.10.0 --python 3.12 python scripts/audit_dependencies.py backend --output /tmp/opencode/r07-audits
uv tool run --from pip-audit==2.10.0 --python 3.12 python scripts/audit_dependencies.py ai --output /tmp/opencode/r07-audits
uv tool run --from pip-audit==2.10.0 --python 3.12 python scripts/audit_dependencies.py ai-upstream --output /tmp/opencode/r07-audits
uv tool run --from pip-audit==2.10.0 --python 3.12 python scripts/audit_dependencies.py emulation --output /tmp/opencode/r07-audits
npm --prefix frontend audit --json
```

| Inventory | Raw advisory rows | Distinct package/advisory-ID pairs | Affected packages | Result |
| --- | ---: | ---: | ---: | --- |
| Frontend full / production-only | 0 | 0 | 0 | Clean feed result |
| Backend | 2 | 1 | 1 | ecdsa0.19.2, reviewed unpatched exception |
| Exact AI lock | 0 | 0 | 0 | **Coverage incomplete:** Torch2.8.0+cpu skipped by PyPI |
| Supplemental upstream Torch2.8.0 | 8 | 8 | 1 | Reviewed frozen-runtime advisory exceptions; not CPU-build certification |
| Frozen emulation pins | 48 | 26 | 8 | Reviewed frozen-runtime exceptions |

Raw JSON and summaries are uploaded separately. Counts deduplicate exact
`(normalized package, version, advisory ID)` tuples, never count feed repetitions as
unique flaws. Aliases are not additional findings. In particular eventlet IDs
PYSEC-2026-1307 and PYSEC-2026-2472 share CVE-2023-29483: the26 emulation pairs are
**not**26 independent CVEs. Do not add upstream-Torch and CPU-wheel results as if
they were independent affected installations.

Authoritative exact exception inventory:
`security/dependency-exceptions.v1.json`. Every entry has owner, exact version/IDs,
reachability rationale, remediation and **2026-10-21 expiry** (fails on that date).

- **ecdsa0.19.2:** PYSEC-2026-1325 (CVE-2024-23342); upstream declines a side-channel
  fix. python-jose requires it; default HS256 plus cryptography backend avoids the
  vulnerable pure-Python signing path. EC signing/configuration changes require
  renewed review. Plan a separately tested JWT-library replacement.
- **Upstream Torch2.8.0:** PYSEC-2025-193/194/195/203/204/206,
  PYSEC-2026-139/2286. Current source has no JIT/PT2/LSTM/unpack_sequence/rot90/LU
  path. **weights_only unpickling is used and is not a security fix**: admit only
  operator-controlled hash-verified immutable checkpoint bytes; compromised trusted
  producers remain a risk. Exact CPU wheel cannot be audited via PyPI; its exact
  skipped reason/version is recorded independently, not normalized away.
- **Emulation:** Ryu4.34(9IDs), eventlet0.30.2(4), dnspython1.16.0(1),
  WebOb1.8.9(2), msgpack1.0.8(1), requests2.31.0(3), idna3.7(1), urllib3
  1.26.19(5). Exact IDs and distinct per-package exposure are in the policy.
  Ryu's OpenFlow parser is reachable from lab switches; malicious switches can DoS
  it. Operator-owned isolated lab use is the bounded exception, not evidence of
  unreachability. Public controller/WSGI/DNS/arbitrary remote URL use is outside it.

### Versioned successor plan (v1, deadline2026-10-21)

1. Preserve historical requirements, wheel/checkpoint/source hashes, image IDs and
   experiment outcomes. Never rebuild under an old qualification identity.
2. Emulation owner creates a **new** successor image/requirements version: replace
   obsolete Ryu/eventlet coupling (`ALREADY_HANDLED` blocks a simple eventlet bump),
   incorporate dnspython≥2.6.1, WebOb≥1.8.11, msgpack≥1.2.1, requests≥2.33.0,
   idna≥3.15, urllib3≥2.7.0, and obtain a fresh audit including OS/build dependencies.
3. AI owner creates a separate CPU environment, targeting at least2.13.0 (highest
   currently advertised fix); review unpatched PYSEC-2026-139 applicability and the
   exact CPU SBOM. Run deterministic load/tamper/tensor/seed regressions without
   retuning historical weights. Do not replace the incumbent environment in place.
4. Exercise malformed OpenFlow, HTTP trailers/redirects, DNS, compressed responses,
   MessagePack error reuse and checkpoint hostile-input boundaries. Run isolated
   controller/parser tests before any explicitly admitted live campaign.
5. Bind successor source/image/model identities and perform the existing required
   requalification. Promote only with retained source-matched evidence. If delayed,
   the gate fails at expiry; a new reasoned review is required, not automatic renewal.

Container image/SBOM security is a separate uncompleted release obligation. The
Python/npm gates do not imply that digest-pinned OS images have no advisories.

## Portable CI breadth and private-history boundary

`quality.yml` now runs `scripts/run_portable_tests.py` with the locked backend
interpreter. It discovers **all `deploy/` tests** (including root lifecycle tests),
all emulation tests and all root-script tests. Separate processes prevent deployment
entrypoint umask changes contaminating filesystem permission tests. The combined
JUnit report must contain executed cases and zero skips/errors/failures.

The runner records exact exclusions, not broad names or best-effort skips:
three Ryu parser cases, one Mininet case, two privileged SDN/FRR lab cases, and five
root-script historical cases. The latter require exact ignored checkpoints/source
archives/frozen interpreter/private completed campaign. Synthetic fixtures already
exercise archive traversal, permissions, ownership, tamper, thresholds and evidence
publication in public CI; they are not substituted for historical qualification.

Existing backend historical-artifact exclusions and the five AI public modules
remain explicit. A clean temporary tree without `artifacts/` executed166AI tests.
A diagnostic all-AI collection hit two missing-history modules; excluding those
gave282pass/150missing-history-related failures. This confirms why full-history
acceptance must remain a separate operator lane. That lane needs privately
provisioned checksum-verified artifacts and original interpreters, then the exact
historical suites, with zero skips; it must not run untrusted PR code on a persistent
artifact-bearing host or publish raw artifacts. No fake release manifest was made.

`fullstack-regression.yml` consumes the sibling's `scripts.review_fullstack`
orchestrator: pinned Neo4j/Redis pulled to a disposable hosted runner, local owned
PostgreSQL, lock-matched browser, actual production assets/HTTP/workers, five
mandatory zero-skip browser cases. Only its sanitized result JSON is uploaded.
Detailed boundaries: `ReviewClosure-Fullstack.md`. It is not cold-backup restore or
physical-model qualification. CI was syntax-checked locally, not executed remotely.

## Executed checks and parent integration findings

- All four Python audit lanes pass their reviewed policy; npm full and production
  audits return0. Nine policy regression tests verify duplicate counts, exact
  version/lane/ID matching, expiry, missing rationale, skipped-feed failures,
  stale-report rejection and incomplete-inventory failure.
- Backend final candidate: **3907passed,314skipped,1failed** on current concurrently
  edited source. Failure:
  `test_telemetry_endpoints.py::test_flow_aggregation_rejected_before_query` expects
  a domain message but receives generic `Request validation failed.` It reproduces
  with original FastAPI0.115.14/Starlette0.46.2; parent/source owner notified.
  No failure exclusion was added. PostgreSQL/Redis opt-in skips are not acceptance.
- Isolated frontend snapshot: **582unit tests passed**; lint, typecheck, production
  bundle budgets pass (**393.43KiB total gzip**,56.78KiB largest non-Three chunk).
  Browser suite **69passed/1failed**, no retries. `spatial-geometry.spec.ts` sees
  zero canonical shapes via its Vite `_roots` inspection; it reproduces standalone
  and with original dependencies. Parent notified; not represented as a pass.
- AI166passed both in repo and a no-artifact temporary tree; `uv pip check` passes
  AI25packages/backend66packages. AI runtime lock entries unchanged, proven by
  parsed comparison against Git HEAD. Backend `poetry check --lock` passes.
- Portable suite: **408JUnit cases, zero skips**: deployment248passed
  (+37subtests), emulation115passed/6explicit deselections (+70subtests), root
  scripts45passed/5explicit deselections (+42subtests, including the sibling's
  public evidence-hygiene cases). Subtests are reported separately rather than
  inflated into top-level case totals. New concurrent cases explain the increase
  over the historical emulation111 count.
- Ruff for new scripts and actionlint1.7.7 for workflows pass (shellcheck unavailable).
  `git diff --check` passes. No commits, shared stores, model installs or live lab.
- Full-stack harness17tests pass under the upgraded backend environment. Its new
  workflow follows the sibling's documented invocation; live/remote acceptance
  remains pending. The original emulation requirements SHA-256 remains
  `a5c31f09953e22b84658e44f0b9cef0e860df3be11881cba06451066be058016`.

Temporary evidence: `/tmp/opencode/r07-audits`, `r07-backend-final.xml`,
`r07-portable*.xml`, `r07-ai-expanded.xml`, `r07-frontend/test-results`.
The parent owns final source freeze, aggregate tracking and source-matched release
acceptance. Fresh sibling changes after the snapshot require integration checks.

## Independent review follow-up — three P2 gate repairs (2026-09-21)

1. **Malformed successful audit response:** reproduced the old behavior with an
   exact-name/version dependency record lacking `vulns`: it returned zero findings
   and no errors. Report validation now requires the pinned pip-audit2.10 JSON
   schema (`dependencies` and empty `fixes`; upstream emits no schema-version
   field). Every dependency must have an explicit valid `vulns` list or an explicit
   skip record that separately matches the reviewed exact-version/reason policy.
   Missing/null/wrong-type lists, malformed names/PEP440 versions, malformed advisory
   IDs/aliases/fix versions/descriptions, duplicate dependency records/JSON keys,
   ambiguous skip+vulns records and unknown schema fields fail closed. Policy
   schema version must be integer1 (not bool/string); entry types and IDs are
   validated too. Failed validation removes stale clean summaries. Main-entry
   regressions supply exact inventories and tool exit0 to prove this cannot pass.
2. **Retention skipped in CI:** confirmed the fixture skips when
   `STREAM_RETENTION_TEST_IMAGE` is missing. Added required `stream-retention` job
   in `disposable-integration.yml`, independent of the optional manual database
   toggle. It pulls the existing digest-pinned Redis7.4.5 image, resolves/verifies
   its full `sha256:` local ID, and supplies that ID to the existing exact-owned
   disposable fixture. All retention cases run; JUnit requires at least27 cases
   and zero skipped/failure/error nodes. No external Redis URL or shared store is
   accepted. Actual local run: **27passed, zero skips**, cleanup assertions passed,
   original shared container IDs unchanged. Image ID:
   `sha256:90e7a336d044f1abc9e9dbc05d65566850896d11453bbd1dd0fb7e5059f0e8fb`.
3. **nginx auth test executed before installation:** confirmed prior workflow order
   installed nginx only after the general suite, then selected only header tests.
   `quality.yml` now explicitly runs
   `test_proxy_boundary.py::test_real_nginx_two_login_clients_and_untrusted_spoof`
   after installation, in a dedicated report. Its JUnit gate requires that exact
   case and zero skips/failures/errors. Actual local case: **1passed, zero skips**.
   Existing header tests remain required with a separate zero-skip gate.

Fresh four-lane advisory queries passed strict schema validation with the same
reviewed residuals (backend1pair, emulation26pairs, upstream Torch8pairs and the
exact CPU gap). No exceptions were expanded. Audit regressions:16tests passed;
Ruff, actionlint1.7.7 and whitespace checks passed. No application files changed.

**Additional parent handoff:** the combined local nginx run produced1proxy pass
and6header-fixture setup errors: the existing `test_gateway_headers.py` substitutes
the former `http://api:8000` upstream but does not provide the now-required
`/etc/nginx/nginx-upstream.conf` include. `nginx -t` reproduced that exact missing
file. The new proxy fixture supplies a private upstream include correctly and
passes independently. Header checks remain failing rather than weakened or
excluded; the owning test/deployment agent must update that fixture. No system
nginx files were created to disguise the failure.

Evidence: `/tmp/opencode/r07-review-retention.xml` (27pass),
`r07-review-proxy.xml` (1pass), `r07-review-nginx.xml` (initial1pass/6errors),
`r07-review-audits/` (four fresh raw reports/summaries). Remote CI execution remains
pending; local execution used the isolated backend interpreter.

## Clean-environment Lua declaration repair (2026-09-21)

Parent's full upgraded-environment PostgreSQL run initially recorded
**17failed /237passed /12skipped (266selected)**. All17failures were autonomous
execution tests encountering fakeredis `unknown command 'eval'`: the shared
original environment contained undeclared lupa2.8, while the clean locked
environment correctly omitted it. A direct EVAL reproduced the missing command
before this repair. Those failure counts remain part of the acceptance history.

Declared **`fakeredis[aioredis,lua]`** in backend development dependencies and
regenerated `poetry.lock`. fakeredis stays2.37.0; its `lua` extra now pulls
**lupa2.8**, development group only, with lock hashes. Installed the resulting
inventory exclusively into `/tmp/opencode/r07-backend`; `uv pip check` verifies
67packages. Added `scripts/check_fakeredis_lua.py` to clean quality and disposable
database CI: real sync/async EVAL rejects stale ownership, accepts the matching
generation and verifies actual stored values. No production Lua, mocks or domain
assertions changed. No frozen/model environment changes.

Executed after repair:

- Full actual `scripts.audit_isolated_suite`, all266selected:
  **254passed /0failed /12Redis-dependent skips**,85.39s.
  Every previously failing autonomous-execution case passed.
- `/tmp/opencode/nanfo_review_redis.py`, separate owned PostgreSQL plus exact-owned
  Redis image: **12passed /0failed /0skipped**,10.91s. These are precisely the12
  skipped cases above, so all266selected cases executed successfully across the
  two runs; the PG-only report is honestly still marked `partial`.
- Both runs confirmed owned children reaped, ports closed and private trees
  removed; Redis container/volume cleanup assertions passed. Existing shared
  container IDs were unchanged.
- Backend re-audit including lupa: no new advisory, existing ecdsa1distinct pair
  (2raw rows) remains the only reviewed backend exception. Poetry lock check,
  dependency consistency,16audit-policy tests, Ruff and workflow lint passed.
- Broad tracked/untracked evidence scan exceeded120s and is not claimed passing.
  Targeted scan of both manifests, Lua checker and changed workflows found the
  stale exact fixture hash for `disposable-integration.yml`. Notified parent/
  evidence owner and refreshed only that hash in `security/evidence-fixtures.v1.json`
  to `853d01414a72c2d6288a5c01c2f3ff7f8bd051de7df878e4078387d8296e4cfe`.
  Its public-fixture credential rule/reason are unchanged.
  Final targeted six-file scan is clean; all20evidence-hygiene regressions pass.

Evidence: `/tmp/opencode/r07-lua-postgres.json`, `/tmp/opencode/r07-lua-audit/`,
and the retained tool output for the12case Redis runner (which deletes its private
JUnit/log tree on successful cleanup). No commits.

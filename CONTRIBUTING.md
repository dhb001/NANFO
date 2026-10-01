# Contributing to NANFO

Thank you for helping. This guide covers the local setup, how changes are proposed,
the exact test commands CI runs, the private-evidence lanes CI cannot run, and how the
owner applies branch protection. Security reports never go through public issues or
pull requests: see [SECURITY.md](SECURITY.md).

Binding design rules live in [`AGENTS.md`](AGENTS.md), `.agents/rules/` (constitution,
architecture guardrails, coding, testing and security rules) and the ADRs in
[`docs/adr/`](docs/adr/). Where this file and an ADR disagree, the ADR wins.

## Ground rules

- **One pull request per finding.** A finding is one review finding or ADR contract
  (for example `ADR-028 C22`, `R06`), one issue, or one Dependabot group. Do not mix
  unrelated fixes, refactors or formatting into it; split them.
- Every fix ships with a regression test next to the code it covers. Never weaken or
  delete assertions, add skips, or `--deselect` tests to make CI pass.
- API changes keep the `{success, data, meta, errors}` envelope and are additive unless
  an ADR marks them **BREAKING**.
- **Frozen runtimes stay frozen** (ADR-028 §1): the historical lab image and its pins,
  the qualified AI runtime (including `torch 2.8.0+cpu`), campaign source snapshots and
  historical evidence. They change only as reviewed successor artifacts.
- Never commit secrets, `.env` files, `deploy/state/`, `ai-engine/artifacts/`,
  receiver tokens or other private evidence. CI fails on them (see *Evidence hygiene*).

## Development setup

Prerequisites (the versions CI uses):

| Tool | Version | Source of truth |
| --- | --- | --- |
| Python (backend) | 3.12.14 | `backend/.python-version` |
| Python (AI engine) | 3.12.14 | `ai-engine/.python-version` |
| Poetry | 2.4.1 | `.github/workflows/quality.yml` |
| uv (AI engine) | 0.8.22 | `.github/workflows/quality.yml` |
| Node.js / npm | 22.22.0 | `.github/workflows/quality.yml` |
| Docker + Compose | Compose with `up --wait --wait-timeout` | `scripts/dev-start.sh` |

```bash
# Stores (PostgreSQL 17, Neo4j 5.26, Redis 7.4 with an ACL user) on loopback only,
# using the production image digests. Generates a private backend/.env (mode 0600)
# with APP_ENV=development and fresh secrets only when it does not exist yet.
./scripts/dev-start.sh

cd backend
poetry sync --with dev --no-root    # exact lock, same as CI
make migrate                        # alembic -c alembic/alembic.ini upgrade head
make dev                            # uvicorn on 127.0.0.1:8000
```

```bash
cd frontend
test -e .env || cp .env.example .env
npm ci
npm run dev -- --host 127.0.0.1 --port 5173
```

Create a local login with the bootstrap snippet in the [README](README.md#3-create-a-local-bootstrap-user-required).
Stop the stores with `./scripts/dev-stop.sh` (`--purge` also deletes their volumes).

Notes:

- The dev PostgreSQL volume is `postgres17_data`. Data in an older major's volume is not
  upgraded in place; recreate it with `make migrate` (development data only).
- Every backend `Settings` field is documented in `backend/.env.example`; adding a field
  without documenting it fails `tests/unit/test_env_example.py`. Never copy the sample
  over a generated `.env`.

## Commit messages and pull request titles

```
Type(area): imperative summary [FINDING-ID]
```

- **Type**: `Feat`, `Fix`, `Security`, `Perf`, `Refactor`, `Test`, `Docs`, `CI`, `Deps`,
  `Chore` or `Revert`. The existing `Feat: …` history is the same form without an area.
- **area** (optional, lower case): `backend`, `db`, `frontend`, `twin`, `ai`, `emulation`,
  `deploy`, `ci`, `security`, `evidence`, `docs`.
- **`[FINDING-ID]`** is required when the change addresses a finding or contract, for
  example `[ADR-028 C22]`, `[R06]` or `[#123]`.
- Body: what changed and why, plus the test commands you ran. Changes an ADR marks as
  breaking add a `BREAKING: <what callers must do>` line.

Examples:

```
Fix(ci): serve the production build through deploy/nginx.conf [ADR-028 C22]
Feat(backend): require a distinct approver for autonomous mode [ADR-028 C25]
Deps(frontend): bump the frontend-minor-patch group
```

Dependabot uses the same form (`Deps(actions)`, `Deps(backend)`, `Deps(frontend)`,
`Deps(ai)`, `Deps(images)`; see `.github/dependabot.yml`).

## Pull requests

1. Branch from `main` (for example `fix/adr-028-c22-gateway-lane`).
2. Keep the PR to one finding and fill in the pull request template.
3. Run the commands below for every area you touched and paste the results.
4. All required checks must pass and the branch must be up to date with `main`.

## Test commands (identical to CI)

### Backend (`cd backend`)

```bash
poetry run ruff check app tests scripts                       # make lint
poetry run python ../scripts/check_fakeredis_lua.py
poetry run pytest scripts/test_audit_isolated_suite.py --no-cov -q
poetry run pytest tests/unit tests/integration -q -m "not private_artifacts"   # make check = lint + this
```

While iterating, run targeted tests: `poetry run pytest <paths> -q --no-cov -p no:cacheprovider`.

CI additionally enforces a coverage floor (`COVERAGE_FLOOR` in `quality.yml`: the measured
baseline minus one point, currently 84 from 85.60% measured with CI's exact command on
2026-09-25; raise it together with the baseline, never lower it) and a skip
budget: `.github/scripts/ci_gates.py` fails when any skip reason exceeds its count in
`.github/ci-skip-budget.json`, and every allowlisted reason must execute in another lane.

Deployment, emulation, root-script and CI-gate suites (zero skips allowed):

```bash
poetry run python ../scripts/run_portable_tests.py --junitxml=portable-results.xml
```

Real nginx gateway gates (need `nginx` on `PATH`):

```bash
poetry run pytest --no-cov -q tests/unit/test_proxy_boundary.py::test_real_nginx_two_login_clients_and_untrusted_spoof
NANFO_TEST_NGINX=1 poetry run pytest tests/integration/test_gateway_headers.py --no-cov -q
```

Database contracts and migrations need a **disposable** PostgreSQL 17 and Redis 7.4;
never point them at a database you care about. The `DATABASE_SUITES` list and the
`*_TEST_DSN` / `*_TEST_REDIS_URL` variables are in
`.github/workflows/disposable-integration.yml`; a drift guard fails when a new DSN-gated
suite is not listed there. Alembic reads its database from `Settings` (`backend/.env`
unless `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD` and
`POSTGRES_DB` are set in the environment); export those for a disposable database, as
the `migrations` job does, before the round trip:

```bash
poetry run alembic -c alembic/alembic.ini heads      # exactly one head
poetry run alembic -c alembic/alembic.ini upgrade head
poetry run alembic -c alembic/alembic.ini check
poetry run alembic -c alembic/alembic.ini downgrade -1
poetry run alembic -c alembic/alembic.ini upgrade head
```

### Frontend (`cd frontend`)

```bash
npm ci --no-audit --no-fund
npm run lint
npm run typecheck
npm test
npm run perf:bundle                  # production build + bundle budgets
npx --no-install playwright install --with-deps chromium
npm run test:e2e -- --project=chromium --retries=0 --workers=2
```

`npm run api:check` (CI job `api-contract`, not required) fails when the committed
`src/shared/types/generated/openapi.ts` differs from the backend's OpenAPI schema; it needs
the locked backend Poetry environment. Regenerate with `npm run api:types` after changing
an API contract.

### AI engine (`cd ai-engine`)

```bash
uv sync --locked --group dev
uv run --no-sync ruff check src tests scripts/shadow scripts/shadow_evaluate.py scripts/agent_runtime
uv run --no-sync pytest -q
```

CI's `ai` job runs this whole suite. The modules listed in
`ai-engine/tests/private_artifacts.txt` replay the ignored `ai-engine/artifacts/` store;
without it each skips with one explicit reason, and the `ai` skip budget allows exactly
one such skip per registered module.

### Dependency audits, packaging and the production browser lane

```bash
python -m pip install pip-audit==2.10.0
python scripts/audit_dependencies.py backend --output audit-results   # lanes: backend ai ai-upstream emulation emulation-frozen
(cd frontend && npm audit --audit-level=low)
```

Exceptions live in `security/dependency-exceptions.v1.json`; each has an owner, an
expiry and a remediation plan, and an exception that no longer matches a lock fails.
Packaging (`packaging.yml`: hadolint, `docker compose config`, image builds, `nginx -t`
in the gateway image, trivy) and the production browser lane (`fullstack-regression.yml`,
ADR-028 C22: same-origin build served through the real `deploy/nginx.conf`) need Docker
and run in CI; read those workflows for the exact local equivalent.

## Private-artifact lanes

Some tests need material that is never published: the ignored evidence store
`ai-engine/artifacts/`, privileged labs, pinned historical images or owner hardware.
CI excludes them explicitly and visibly, never silently:

- **Backend `private_artifacts` marker.** Tests listed in
  `backend/tests/private_artifacts.txt` are marked `private_artifacts` by
  `backend/tests/conftest.py`. With the store present they run as part of the normal
  suite; alone:

  ```bash
  cd backend && poetry run pytest -m private_artifacts -q --no-cov -p no:cacheprovider
  ```

  Without the store they skip with an explicit reason. A new test that reads the store
  must be added to that registry; workflows never use `--deselect`.
- **AI engine private modules.** Modules listed in `ai-engine/tests/private_artifacts.txt`
  call `private_store.requirePrivateStore()` and carry the `private_artifacts` marker; with
  the store present run them with `cd ai-engine && uv run --no-sync pytest -m private_artifacts`.
  Registering another module needs a reviewed bump of the `ai` lane in
  `.github/ci-skip-budget.json`.
- **Owner opt-in lanes.** Every other skip reason, and the variable that enables it,
  is listed in `.github/ci-skip-budget.json` (for example `RUN_DISTRIBUTED_REALTIME=1`,
  `FLEET_LOCAL_SNMP=1`, `NANFO_TEST_ADR013_CAMPAIGN_ROOT`).
- **Portable-lane boundary.** `EXCLUSIONS` in `scripts/run_portable_tests.py` names the
  emulation and research-script tests that need pinned lab images, privileged SDN/FRR
  labs or ignored historical artifacts. Run them on an owned lab host, for example
  `PYTHONPATH=.:backend:scripts python -m pytest '<node id>'` from the repository root.

Results from these lanes are evidence: record where and how they ran, never commit
their raw outputs, and never replace missing historical inputs with invented ones.

## Evidence hygiene and secret scanning

Before committing, scan what you are about to add:

```bash
python3 scripts/evidence_hygiene.py scan --root . --tracked --include-untracked \
  --fixtures security/evidence-fixtures.v1.json \
  --location-exceptions security/evidence-location-exceptions.v1.json
```

It fails on credentials, private keys, tokens and credential URLs (including inside
archives), and on private locations such as `deploy/state/`, `ai-engine/artifacts/`
or `.env` files anywhere in the tree, campaign source snapshots included. Reviewed
synthetic fixtures are pinned by SHA-256 in `security/evidence-fixtures.v1.json`; editing
such a fixture needs a reviewed re-pin in the same PR.

The only location exception is the owner's decision of 2026-09-24 for the 10 ADR-023
deployment-verification copies under
`nanfo-experimental-campaign-014/source/deploy/state/adr023-private-evidence/`: the
campaign's `plan.json`, `offline-gates.json` and `seed-audit.json` pin each file by path
and SHA-256, and their content scan is clean, so they stay tracked. The exception in
`security/evidence-location-exceptions.v1.json` names each exact path with its SHA-256;
any changed byte, rename or additional file in a forbidden location still fails, and so
does an exception whose file is gone. Purging these copies with a history rewrite remains
an owner option (ADR-028 §5).

CI also runs `gitleaks` over the entire history with `.gitleaks.toml`; its only accepted
credentials are the 71 expired receiver tokens pending the owner's history rewrite
(ADR-028 §5), and other accepted findings are reviewed false positives: pinned to exact
historical commits in `.gitleaksignore`, or, for code not yet committed, allowlisted in
`.gitleaks.toml` by exact file and exact extracted expression.

## Branch protection (owner action)

The protection for `main` is prepared in [`.github/rulesets/main.json`](.github/rulesets/main.json)
(ADR-028 §5: applying it is an owner action). It requires a pull request with resolved
review threads, blocks force pushes and branch deletion, and requires these checks,
each reported by GitHub Actions (`integration_id` 15368) on an up-to-date branch:

<!-- required-checks:start -->
- `backend`
- `frontend`
- `ai`
- `python-inventories`
- `npm-lock`
- `evidence-hygiene`
- `database-contracts`
- `migrations`
- `stream-retention`
- `production-browser`
- `packaging`
- `gateway-proxy-boundary`
- `gateway-headers`
<!-- required-checks:end -->

Rulesets on a **private** repository need GitHub Pro, Team or Enterprise; on GitHub Free
they are available for public repositories only. To apply (repository admin, `gh` 2.x
logged in with the `repo` scope):

```bash
# 1. Merge the workflows first and let one pull request run every check above once.
# 2. Create the ruleset.
gh api --method POST repos/dhb001/NANFO/rulesets --input .github/rulesets/main.json
# 3. Verify what now applies to main.
gh api repos/dhb001/NANFO/rules/branches/main
```

To update it after editing the file:

```bash
id="$(gh api repos/dhb001/NANFO/rulesets \
  --jq '.[] | select(.name == "main: pull requests with required checks") | .id')"
gh api --method PUT "repos/dhb001/NANFO/rulesets/$id" --input .github/rulesets/main.json
```

The same can be done in the web UI (Settings → Rules → Rulesets → New ruleset → Import
a ruleset) with the same file. A required check that never reports blocks every merge,
so keep job names in sync with the list above; `.github/scripts/test_workflows.py`
fails when they drift.

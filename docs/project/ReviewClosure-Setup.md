# ADR027 setup/proxy closure — R05, R06 and scoped R12

Date: 2026-09-21. Implementation and isolated regression evidence; deployment
acceptance remains with the coordinating owner.

## Delivered

- **R05 development exposure:** all four published store ports bind explicitly to
  `127.0.0.1`. Compose has no fallback passwords and requires all four credentials.
  The sample has empty secrets, so copying it cannot start the stores automatically.
- **Local provisioning:** `scripts/dev-start.sh` generates four independent
  32-byte random hex secrets into a complete mode-0600 file, atomically published
  only if `.env` does not exist. Existing files and dangling symlinks are preserved;
  env content is never executed. Effective Compose credentials, including shell
  overrides, are validated privately before startup. Neither generated secrets nor
  rendered Compose configuration are printed. Existing populated volumes retain
  their credentials: provision the matching existing env rather than generating
  replacement credentials for an already initialized store.
- **Production settings:** environments other than development/dev/test/testing
  reject empty, short, control-character and known placeholder credentials. Store
  passwords require at least16 characters; JWT keys require32. Error strings and
  settings repr omit secret values. Valid custom punctuation/URI credentials are
  preserved exactly. `EXECUTION_MODE=production` alone does not break test fixtures;
  `APP_ENV` selects the environment policy.
- **R12 startup and migration:** `make up` uses the validated setup path. Compose
  must support `up --wait --wait-timeout`; unsupported versions fail before startup.
  Health wait defaults to180 seconds, configurable with `NANFO_DEV_WAIT_SECONDS`
  (1–3600). Unhealthy/timeout failure returns nonzero without a success message.
  Neo4j readiness probes HTTP instead of merely checking process existence. Both
  migration targets use `alembic -c alembic/alembic.ini`. The setup completion message
  explicitly identifies healthy stores; API/workers remain separate processes.
- **R06 proxy attribution:** Uvicorn explicitly enables proxy headers, defaults to
  an empty trust list in the image, and receives exactly nginx's private IP from
  Compose. Existing nginx overwrite directives for X-Forwarded-For and
  X-Forwarded-Proto are retained. No wildcard, public-peer trust, or entire shared
  store/worker subnet trust is introduced.

## Proxy boundary and deployment handoff

Previous topology: gateway, API, workers and stores shared `private`; gateway also
joined `gateway` for its loopback-published host port. New proxy-only topology:

```text
host loopback -> nginx [gateway + internal proxy]
                         |
                   API / optional API2 [internal proxy + internal private]
                                                               |
                                                     workers and stores
```

The gateway leaves the datastore network. Only gateway and serving APIs join the
new internal `proxy` network. API ports remain unpublished. Distributed/fleet/live-AI/
autonomous-client overlays inherit the same API trust/network settings, including
API2; rendered combinations are regression-tested.

Default proxy subnet: `172.30.27.0/24`; exact gateway address: `172.30.27.2`.
For each concurrent deployment or restore project, choose a distinct unused private
subnet and gateway address **before network creation**. Set the matched pair in that
project's private `deployment.env`, for example:

```dotenv
NANFO_PROXY_SUBNET=172.29.123.0/24
NANFO_PROXY_GATEWAY_IP=172.29.123.2
```

These are network configuration, not credentials. Choose values appropriate to the
host's existing routes/networks; never substitute a public address, CIDR trust list,
or `*` for the gateway IP. Compose uses the same variable for nginx's fixed address
and Uvicorn trust, preventing independent drift. Docker rejects conflicting pools
or an invalid fixed address at network creation. Only host administrators may
attach containers to this boundary; Docker administration is already root-equivalent.

Coordinator acceptance: rebuild the backend image and apply the network config to
fresh owned projects; give source and restore projects distinct subnet/IP pairs.
Run source-matched deployment/backup/fresh-restore checks there. The real forwarding
test below uses loopback source addresses to model the exact trusted Docker peer;
it does not claim a newly deployed Docker image or Docker-network packet capture.
External load balancers/NAT may intentionally collapse source IPs before nginx;
this configuration attributes nginx's actual peer and does not trust their headers.

## Validation

New tests:

- `backend/tests/unit/test_setup_settings.py`: non-development rejection matrix,
  redacted errors, valid custom credentials, test/development compatibility.
- `backend/tests/unit/test_dev_setup.py`: copied-script execution against a fake
  daemon with actual read-only Compose rendering; private generation, existing-env
  preservation, unsafe ambient overrides, literal env parsing, dangling symlink,
  health-wait success/failure/version/timeout validation, sample refusal, port binds,
  and migration dry-runs. No actual Compose startup occurs.
- `backend/tests/unit/test_proxy_boundary.py`: default image trust, resolved overlay
  topology, HTTP/WebSocket exact-peer trust and public/private untrusted spoofing.
  Real local nginx and Uvicorn exercise the actual login route/service with fake
  persistence: client1 reaches429, client2 remains401 with its independent bucket,
  and an untrusted direct client retains its own IP. Audit IPs agree. Forged XFF
  identities and the proxy address never acquire rate-limit buckets. Owned child
  process and ephemeral sockets are closed in teardown.

Commands from `backend/`:

```sh
poetry run pytest --no-cov -q tests/unit/test_setup_settings.py tests/unit/test_dev_setup.py tests/unit/test_proxy_boundary.py tests/unit/test_config_dsn_safety.py tests/unit/test_distributed_config.py
PYTHONPATH=..:. poetry run python -m pytest --no-cov -q ../deploy/tests/test_adr023.py ../deploy/tests/test_operations.py ../deploy/test_lifecycle.py
poetry run ruff check app/core/config.py tests/unit/test_setup_settings.py tests/unit/test_dev_setup.py tests/unit/test_proxy_boundary.py
poetry run alembic -c alembic/alembic.ini heads
```

Results: focused setup/proxy/settings/DSN/config lane **226 passed**; existing
deployment topology/operations/lifecycle lane **136 passed**. Ruff and shell syntax
checks passed; Alembic reports **0029 (head)** without migration. Only upstream
deprecation warnings occurred. An initial test import typo, deployment import-path
invocation and transient concurrently changing pytest installation were corrected
before these successful runs.

### Upgraded dependency runtime: actual nginx fixture repair

The parent assigned `backend/tests/integration/test_gateway_headers.py` after the
dependency owner found its obsolete inline `http://api:8000` replacement left the
current `/etc/nginx/nginx-upstream.conf` include unresolved. The fixture now writes
an isolated temporary `upstream nanfo_api` include pointing at its ephemeral
loopback HTTP server and substitutes only that include path. This avoids Docker
DNS and host-nginx version dependence on dynamic upstream `resolve`. Production
proxy/header directives and all six status/security-header assertions are intact.
The nginx syntax check is bounded; child termination has a kill fallback and
upstream cleanup runs even if nginx teardown fails. No deployment source changes.

Executed from `backend/` using the dependency owner's upgraded Python3.12.14 env:

```sh
NANFO_TEST_NGINX=1 /tmp/opencode/r07-backend/bin/python -m pytest --no-cov -q tests/integration/test_gateway_headers.py tests/unit/test_proxy_boundary.py
/tmp/opencode/r07-backend/bin/python -m ruff check tests/integration/test_gateway_headers.py tests/unit/test_proxy_boundary.py
```

**24 passed, zero skips** (six actual-nginx header cases plus18 proxy-boundary
cases); Ruff passed. Two upstream websockets deprecation warnings remain. This
includes the real nginx/Uvicorn two-client login-rate-limit and direct untrusted
spoof regression. All listeners/processes are fixture-owned; no shared service or
Compose startup was used.

Shared services, existing env files, README/global tracking and Git history were
not changed. No commits. R12 repository organization, licensing and broader
full-stack onboarding remain coordinating-owner scope.

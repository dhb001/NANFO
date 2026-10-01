# ADR020 Operations Interface

These tools require host Python 3.12+, `cryptography`, Docker and Compose v2.
No application packages are installed into the frozen AI runtime. Run from the
repository root, or invoke the scripts by absolute path. All Docker operations
require an explicit `nanfo-deploy-*` project, Compose file(s), and env file.

## Backup

Provision a separate owner-only file containing exactly 32 random raw key bytes
through the operator's secret manager. This tool does not generate or recover the
key. Keep it outside the backup directory tree (not inside the backup directory or
beside it in the same parent: the tool refuses both), mode 0600, and escrow it
separately; a key on the same filesystem as the backups draws a warning.
The existing destination directory must be operator-owned, empty, mode 0700.

```sh
python3 deploy/backup_restore.py backup \
  --project nanfo-deploy-source \
  --compose-file deploy/compose.yaml \
  --env-file /protected/source/deployment.env \
  --directory /protected/backups/checkpoint \
  --encryption-key-file /protected/keys/backup.key
```

Repeat `--compose-file` for each deployed overlay, including lab/AI. Freeze
host-side model/registry/binding producers and serialize operator/Docker activity
for the entire operation. Docker inspection cannot fence an unrelated host process.
Do not use `manage.py stop` as a substitute for the safety checkpoint.

The tool first inventories and measures every volume and backed bind read-only, and
refuses **before stopping anything** if a source exceeds `--max-volume-bytes` or the
destination lacks free space for the estimate (+5% and 64 MiB). It then stops
gateway/API admission. Intent/Autonomy owner services refuse
unresolved execution, uncertain cancellation, active controls and unresolved timed
overrides before recovery workers are stopped. On refusal, recovery workers and
stores remain available; gateway/API remain stopped. Resolve through their existing
owner workflows, not SQL updates or forced successful status. After all writers
(workers and the supervised retention/asset services) stop, a second checkpoint precedes
clean store shutdown. Every owned local named volume is copied, including PostgreSQL, Redis
AOF/streams, Neo4j application/system data, reports, network assets, the telemetry and
stream archives (schema 0030+ refuses a backup without `stream_archive`),
command/result/output mailboxes and the encrypted per-role secret volumes.
No migration, logical-only dump, stream trim, FLUSHDB or physical command replay.

Read-only external binding/model/registry directories receive separate encrypted
archives in `manifest.binds`. Unknown regular bind mounts, anonymous/external
volumes, dirty store shutdowns and uncovered persisted model references are refused.
Compose secret files are keyed-fingerprinted; restore requires their original
identical bytes. Source host paths are not exposed.

**Format 2 (current).** HKDF-SHA256 derives separate archive-encryption, manifest-MAC
and fingerprint keys from the 32-byte master key (salt `NANFO-backup-v2`, info
`nanfo-backup/v2 <purpose>`). Each archive (`NANFO-GCM-2` header) is AES-256-GCM in
independently authenticated ≈16 MiB segments; the nonce is a random per-archive prefix
plus the segment counter, and the AAD binds project/archive/volume identity, the header,
the segment index and a final-segment flag, so truncation, reordering, splicing and
tampering fail. The manifest carries an HMAC-SHA256 signature and ciphertext SHA256s;
files are 0600. Format 1 archives (single GCM stream keyed by the master key) remain
restorable and verifiable. Regular files/directories and root-confined links are
supported; traversal, parent-relative links, duplicates, special permission bits and
device/FIFO/sparse entries fail closed. Default cap is 100 GiB per archive, configurable
up to 1 TiB; validation also caps entries at one million. Use an encrypted local
filesystem/swap and authenticated encrypted off-host transfer.

## Restore

Use the same command with `restore`, a different explicit fresh project/env file,
and the existing backup directory. First prepare configuration only, not `start`
or `initialize`. Reuse exact source image IDs/OS/architecture and original external
secret/config bytes. Bind targets must be different, existing empty directories.
No target containers or volumes may exist. All source owners must remain stopped.
Do not run source and restored physical controllers together.

`verify` authenticates and validates archives without Docker mutation. `restore`
validates every archive before creating any volume: format 2 is checked in a first
streaming pass (every segment authenticated and the tar stream validated, nothing
written) and then decrypted a second time straight into the tar extraction, so no
plaintext is staged. Format 1 needs plaintext staging in `--work-dir` (default: the
backup directory), which must be a private 0700 directory on local, non-network storage
with enough free space (checked first); prefer an encrypted local filesystem. It
then starts only the three
stores, checks readiness/schema and report receipt/bytes through Report ownership,
compares inventory checkpoint counts, invalidates bounded `auth:session:*` families,
and removes only the API realtime lease. Durable streams/jobs/evidence remain.
This is an exact-version cold restore, not a cross-platform or cross-version export.

Failure leaves partial fresh targets for explicit investigation, never removes
resources or automatically resumes services. Successful restore also leaves all
application writers/gateway/lab stopped. Review the recorded image/configuration,
reconcile durable jobs and bindings, then explicitly start the approved services
without initialization/migration. A new login, download with original report hash,
and persisted workflow/telemetry checks are still required for live acceptance.
Do not call an unmarked `manage.py start` on restored volumes: its initialization
path belongs only to empty deployments. The parent package owns resume integration.

## Retention And Diagnostics

```sh
python3 deploy/retention.py --project nanfo-deploy-source \
  --compose-file deploy/compose.yaml --env-file /protected/source/deployment.env \
  --grace-hours 24 --batch-size 100 --telemetry-days 30
python3 deploy/diagnostics.py --project nanfo-deploy-source \
  --compose-file deploy/compose.yaml --env-file /protected/source/deployment.env
```

Retention is dry-run by default and requires stopped application/lab writers with
stores available. Inspect the dry-run before adding `--apply --backup-manifest
/protected/backups/checkpoint/manifest.json --encryption-key-file /protected/keys/backup.key`.
Apply requires an authenticated same-project backup less than 24 hours old. Report
ownership verifies current receipts, refuses any active/legacy job, and pins every
registered filename before bounded descriptor-relative cleanup of canonical
UUID-UUID CSV/PDF attempt files at least 24 hours old. Symlinks, hardlinks, unknown
names, recent files and uncertain inventories are never cleanup candidates.

`retention.py --telemetry-days` remains an assessment that reports a bounded aged-row
count; telemetry rows are deleted only by the supervised `telemetry-retention` loop, and
domain-stream/DLQ entries only by the supervised `stream-retention` loop, both strictly
archive-before-delete into their private archive volumes (pending stream entries are
never eligible). No audits, diagnostics/config/alert histories or models are removed.
Diagnostics expose dependency/schema state, outbox counts,
bounded queue/pending/idle samples and PostgreSQL size without payloads or secrets.
Redis's package `noeviction` memory cap refuses new writes rather than evict evidence.
These tools do not implement a PostgreSQL/report disk admission cap; operators must
monitor provisioned storage and stop new work before exhausting it.

## Credential Rotation

```sh
python3 deploy/manage.py --state /srv/nanfo/instance1 rotate --secret redis
# postgres_app | postgres_owner | neo4j | redis | jwt_secret
python3 deploy/manage.py --state /srv/nanfo/instance1 rotate --secret jwt_secret --finalize
```

Rotation needs an initialized, running deployment. For a store credential the new value
is journaled first (`secrets/.<name>.pending`, 0600) and passed to the one-shot
`secret-rotation` helper on **stdin only** (never argv, environment or SQL text): PostgreSQL
receives a client-computed SCRAM-SHA-256 verifier via `ALTER ROLE` and the helper proves a
login with the new password; Redis gets `ACL SETUSER nanfo #<sha256>` from `nanfo-admin`
(the old hash stays valid until every client restarted, then `finalize` keeps only the new
one); Neo4j changes its own password with parameterised `ALTER CURRENT USER`. The value is
then published atomically, restaged into every secret volume holding it, and dependent
services restart (`postgres_owner` affects only the initializer copy). Every step is
idempotent: after an interruption rerun with `--resume`; a plain rerun refuses while a
journal exists. The bootstrap password may be removed from `secrets/` once the deployment
is initialized.

`jwt_secret` (C19) signs with a new key immediately and keeps the previous key
verify-only in `jwt_previous_secrets` (API volume only) for one access-token lifetime plus
leeway (930 s; `--overlap-seconds` up to 43200, the session idle timeout, to spare idle
sessions; `0` revokes every outstanding token). Clients that refresh inside the window
continue without logging in again. The API process keeps the old key until restarted, so
run `rotate --secret jwt_secret --finalize` after the window; a second rotation is refused
until then. `--resume` republishes the recorded keys after an interrupted run. With the
distributed overlay also restart `api2`.

## Autoheal

Restart policies (`unless-stopped`) react to exits, including the backend watchdog's
exit 70; `manage.py autoheal` restarts application containers that stay **running but
unhealthy** for more than `--threshold` consecutive observations (default 3). Datastores,
the lab and one-shot services are never touched, and restarts are deferred while any
datastore is not healthy. Continuous mode sleeps `--interval` seconds (5–3600) between
observations; `--once` performs one observation and keeps the consecutive counts in
`<state>/autoheal.json` (0600) for a systemd timer:

```ini
# /etc/systemd/system/nanfo-autoheal.service
[Unit]
Description=NANFO autoheal (restart persistently unhealthy application containers)
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
User=nanfo-operator
UMask=0077
NoNewPrivileges=yes
ExecStart=/usr/bin/python3 /opt/nanfo/deploy/manage.py --state /srv/nanfo/instance1 autoheal --once --threshold 3

# /etc/systemd/system/nanfo-autoheal.timer
[Unit]
Description=Run NANFO autoheal every 30 seconds

[Timer]
OnBootSec=2min
OnUnitActiveSec=30s
AccuracySec=5s

[Install]
WantedBy=timers.target
```

`User=` is the deployment operator (owner of the 0700 state directory, member of the
`docker` group). Enable with `systemctl enable --now nanfo-autoheal.timer`; restarts are
logged as JSON lines (`{"autoheal": "restarted", "service": ...}`) in the journal.

## Lab Lifecycle

`manage.py lab {start,stop,status}` drives the C23 successor lab (`compose.lab.yaml`,
operator-pinned `NANFO_LAB_IMAGE`); `--frozen` selects the privileged historical image
(`compose.lab.frozen.yaml`, `NANFO_LAB_FROZEN_IMAGE`) and requires `NANFO_LAB_FROZEN=1`.
See `README.md` "Optional Lab". Include the lab overlay in `--compose-file` when backing
up a deployment whose lab is configured.

## Verification Scope

`deploy/tests/test_operations.py` and `test_backup_v2.py` cover isolated crypto (format 2
segment tampering/truncation/reordering, format 1 compatibility), archive safety, strict
resource scope, capacity refusal before any stop, cold ordering/refusal, fresh restore,
bounded session invalidation, model mount requirements, telemetry assessment and report
cleanup protections. `test_adr028_manage.py` covers rotation, autoheal, the lab lifecycle,
key provisioning and the state location; `test_adr028_runtime.py` the supervised services,
per-role secrets, Redis ACL, images, fleet runtime and image surface.
Run with the backend interpreter from the repository root. These tests use no live
Docker resources and do not establish full-stack recovery acceptance; the parent
`deploy/verify.py` campaign owns that verification after package integration.

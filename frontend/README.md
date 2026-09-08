# Frontend Session Behavior

Authentication tokens and workspace selection are persisted in `sessionStorage`,
not `localStorage`. Sessions intentionally belong to one browser tab. Reloading
that tab restores its session after `/auth/me` verification; other tabs must log
in independently. Legacy shared `nanfo.auth.*` and workspace keys are discarded,
not migrated, so an old refresh token cannot be replayed by multiple tabs.
New windows with an opener discard inherited credentials. Application links that
open new tabs must use `noopener`.

Refresh requests are single-flight within the tab and replace both tokens in one
storage write. Logout waits for an in-flight rotation; if the access token has
expired, it refreshes once and retries backend logout before local cleanup.
Network failures clear the local session but display that revocation is unconfirmed.

Before-open WebSocket close code `1006` is ambiguous. The client probes the existing
`/auth/me` endpoint and rotates only on a confirmed `401`. Upgrade recovery is
limited to one conclusive attempt until a connection opens successfully, including
across the resulting token rotation. Inconclusive network/server failures permit
another auth probe after an exponential cooldown (5 seconds, capped at 60 seconds).
Transport reconnects continue with backoff; an outage alone never rotates tokens.

Global plugin registry and telemetry health UI require the Admin role in addition
to the corresponding permission. Active membership is enforced by the backend;
the frontend does not infer membership from roles or local workspace selection.
Tenant telemetry history remains accessible with `read:telemetry`.

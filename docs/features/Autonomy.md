# Feature PRD: Governed Autonomy

ADR-012 is the authoritative Step 9/10 safety/model/authorization contract.
Autonomy owns controls and decision history; online learning is prohibited.
Monitor and recommendation modes never dispatch. Autonomous mode requires a
qualified checkpoint, compatible measured observer, calibrated safety bounds and
server-authorized durable executor. Default missing providers fail closed.

GET /api/v1/autonomy?network_id=UUID returns scoped status and bounded decisions.
PUT /api/v1/autonomy sets mode/model/expiry only after permission and readiness
checks and requires `expected_revision` from the last GET. Stale revisions return
409 and require a fresh explicit user action, not automatic reapproval.
POST /api/v1/autonomy/stop persists an emergency latch and requests verified
cancellation of only owned execution. Responses use success/data/meta/errors.
UI must expose blockers and unresolved operations without conflating mode selection,
decision acceptance, switch verification and measured performance improvement.

Acceptance requires unit/integration authorization and safety tests plus a real
live qualified inference -> safety -> authorized action -> verification scenario.
Missing model/provider/evaluator evidence is a blocker, not a fabricated confidence.

## ADR-028 changes (C17, C25, C26)

Contract index: `docs/api/ADR028-ContractChanges.md`.

- **Confidence (C17).** Proposals and decisions carry typed
  `confidence {value, method, calibrated, calibration_id}`. Autonomous dispatch requires
  `calibrated=true` and `value >= min_confidence` (default 0.95, never lower).
  `allow_uncalibrated_confidence` is honoured only in the enabled experimental lab.
  Refusals record `confidence_missing`, `confidence_uncalibrated`,
  `confidence_below_threshold` or `receiver_confidence_policy_denied`. The frozen model
  reports an uncalibrated `policy_action_probability`, and no calibration exists yet, so
  autonomous dispatch stays blocked outside that experimental-lab exception.
- **Two-person switch (C25).** A `PUT` to `autonomous` by one user returns **202** with
  `meta.pending_approval=true` and a pending request (Redis, at most 1 h, bound to
  revision, mode and checkpoint). An identical `PUT` by a *different* user applies it;
  the same user gets 409 `AUTONOMY_DISTINCT_APPROVER_REQUIRED`.
- **STOP.** Clearing an emergency STOP needs org role Admin (403
  `AUTONOMY_STOP_CLEAR_REQUIRES_ADMIN`). STOP itself is allowed to any member with
  `read:telemetry` while `AUTONOMY_STOP_ALLOW_READ_ONLY` is true. A STOP that cannot latch
  in time returns 503 `AUTONOMY_STOP_BUSY` (`Retry-After: 1`).
- **Audit.** Mode approvals, STOP, overrides and configuration changes are audited.
- **Decisions.** Repeated no-change cycles fold into one decision (`repeat_count`,
  `last_seen_at`). History lists return summaries; `last_decision` is the full record.
- **Model diagnostics (C26).** Locks are per network with per-organisation slots
  (`AUTONOMY_MODEL_DIAGNOSTICS_MAX_PER_ORG`, default 2); busy returns 429
  `MODEL_DIAGNOSTIC_BUSY` / `MODEL_DIAGNOSTIC_ORG_LIMIT` (`Retry-After: 5`).
- **Receipts (C21).** Receiver health receipts are Ed25519-signed (v2, with `key_id`);
  legacy HMAC receipts are accepted only for frozen runtimes.

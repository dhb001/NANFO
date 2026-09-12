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

# Further Model Refinement

## Completed Stage

ADR015 broadened stationary matched conditions to eight profile families. Its
candidate completed512 fresh transitions/32updates with exact raw replay verified.
Validation reward0.66638->0.67951, delivery95.174%->95.503%, RTT38.816->36.931ms,
and switches10->8 across64 decisions. Gain0.01313 and20% switch reduction missed
the preregistered >0.02/25% gates. All anchor/low-load nonregression checks passed,
but no replacement was selected and final seeds remained closed. Preserve this
as modest validation improvement, not demonstrated final improvement.

## Active Continuation

User explicitly authorized further refinement without time preference. ADR016
freezes a new bounded24-hour campaign, tensor-only warm-start from hash-verified
candidate512 with NEW Adam/RNG and32/32 rollout/minibatch balancing all profiles.
Target2048 new transitions, validation at1024/2048 using64 seeds and fresh final
128 seeds if qualified. Seven methods are measured; reference-based promotion
gates and statistical limitations are recorded before collection.

Service: `nanfo-refinement-long-001.service`.
Output: `ai-engine/artifacts/adr016-001/`.
Started2026-09-10 20:59:23 EAT (17:59:23 UTC).
Systemd cap2026-09-11 20:59:23 EAT, with bounded stop/cleanup phase.
Status.json is authoritative; this launch note is not completion evidence.

Verified after launch: first128 transitions/four updates checkpointed and exact
cleanup passed; next session progressed beyond160 transitions/five updates.
No validation/test attempted yet. Independent review checked source/historical
hashes, model-update chain, resource limits and ownership; no critical launch
defect found. All3435 inventoried historical artifacts are unchanged.

## Controls

From `ai-engine/`:

```bash
.venv/bin/python scripts/refinement_long/runner.py status
.venv/bin/python scripts/refinement_long/runner.py stop
```

From any directory:

```bash
systemctl --user status nanfo-refinement-long-001.service
systemctl --user stop nanfo-refinement-long-001.service
```

Keep machine awake and sources/images unchanged. No competing lab. AI service and
Docker lab each have separate2CPU bounds; AI2GiB, lab768MiB/PIDs256. One owned lab,
no public ports, privileged trusted emulation only. No automatic restart, lost-step
retry, indefinite budget extension or autonomous model promotion.

Default remains ADR014 checkpoint
`5b8818af655ec8efce5d3bc3def27db599f3e0df379a0ae263dcefb5f72a80a5`.
No new better-model result is claimed while training is active. If qualification
fails, retain the incumbent. Read `ai-engine/ADR016-LONG-REFINEMENT.md` for exact
frozen thresholds, seed namespaces, resource admission and evidence limitations.

Verification before launch:336 AI tests passed; lint/format passed. Tests verify
implementation, not eventual model performance. The active campaign continues
outside the conversation, with explicit status/stop commands above.

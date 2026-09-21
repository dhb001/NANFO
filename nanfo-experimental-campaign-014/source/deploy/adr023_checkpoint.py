"""Bounded read-only operator integrity checks, never application business queries."""

import asyncio
import hashlib
import json


async def telemetry_archive_checkpoint(db, *, root="/var/lib/nanfo/telemetry-archive", max_rows=10000):
    from app.modules.telemetry.archive import TelemetryArchiveStore
    from sqlalchemy import text

    store = TelemetryArchiveStore(root)
    result = {}
    # Independent hashes bind receipts AND permanent replay/reference exclusions.
    # Fixed operator table inventory; no cross-owner joins or mutations.
    for table, order in (
        ("telemetry_archive_receipts", "record_id"),
        ("telemetry_event_tombstones", "event_id"),
        ("telemetry_evidence_pins", "workspace_id, owner, reference_id, record_id"),
        ("telemetry_reference_coverage", "workspace_id, owner"),
        ("telemetry_reference_reconciliation", "workspace_id, owner"),
    ):
        rows = (await db.execute(text(
            f"SELECT row_to_json(t) FROM {table} t ORDER BY {order} LIMIT :cap"
        ), {"cap": max_rows + 1})).scalars().all()
        if len(rows) > max_rows:
            raise ValueError("Telemetry checkpoint row cap exceeded")
        digest = hashlib.sha256()
        total = 0
        for row in rows:
            if table == "telemetry_archive_receipts":
                body = await asyncio.to_thread(store.read, row["sha256"], row["size_bytes"])
                content = json.loads(body)
                if any(content[key] != row[key] for key in ("record_id", "event_id", "workspace_id")):
                    raise ValueError("Telemetry archive scope differs from receipt")
                total += len(body)
            digest.update(json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n")
        result[table] = {"rows": len(rows), "sha256": digest.hexdigest()}
        if table == "telemetry_archive_receipts":
            result[table]["verified_bytes"] = total
    return result


async def autonomous_execution_checkpoint(db):
    from sqlalchemy import text

    # Verified executions still own resources until exact compensation. Expired
    # leases, revoked actors and restarted processes do not release ownership.
    count = await db.scalar(text("SELECT count(*) FROM autonomous_executions WHERE released = false"))
    return {"safe": count == 0, "unreleased_executions": count}


async def experimental_lab_checkpoint(db):
    """Read-only0028 ownership gate; never resets STOP or releases private lab work."""
    from sqlalchemy import text

    runs = await db.scalar(text("SELECT count(*) FROM experimental_lab_runs WHERE released = false"))
    resources = await db.scalar(text("SELECT count(*) FROM experimental_lab_resources WHERE owner_run_id IS NOT NULL"))
    actions = await db.scalar(text("SELECT count(*) FROM experimental_lab_actions WHERE phase NOT IN ('restored', 'rejected')"))
    return {"safe": runs == resources == actions == 0, "unreleased_runs": runs,
            "owned_resources": resources, "pending_actions": actions}

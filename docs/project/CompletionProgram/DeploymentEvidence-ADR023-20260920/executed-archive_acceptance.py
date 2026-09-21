"""Explicit disposable deployment fixture; never represents measured telemetry."""

import argparse
import asyncio
import hashlib
import json
import os
import sys
import uuid
from datetime import UTC, datetime


async def execute(action, value):
    from app.core.config import get_settings
    from app.db.postgres import AsyncSessionLocal, get_engine
    from app.modules.telemetry.archive import TelemetryArchiveStore, canonical_record
    from app.modules.telemetry.archive_repository import TelemetryArchiveRepository
    from app.modules.telemetry.models import TelemetryRecord
    from app.modules.telemetry.pins import (
        EvidenceOwnerScope,
        EvidenceReference,
        TelemetryEvidenceService,
    )
    from app.modules.telemetry.repository import TelemetryRecordRepository
    from app.modules.telemetry.service import TelemetryPersistenceService
    from sqlalchemy import text

    settings = get_settings()
    if (os.environ.get("NANFO_DEPLOY_ACCEPTANCE") != "isolated-archive-v1"
            or settings.POSTGRES_HOST != "postgres" or settings.POSTGRES_DB != "nanfo"):
        raise ValueError("Only explicitly admitted isolated Compose acceptance")
    workspace, network = uuid.UUID(value["workspace_id"]), uuid.UUID(value["network_id"])
    try:
        async with AsyncSessionLocal() as db:
            assert await db.scalar(text("SELECT version_num FROM alembic_version")) == "0027"
            if action in {"historical", "prospective"}:
                names = ["historical"] if action == "historical" else ["archive", "pinned"]
                result = {}
                for name in names:
                    event = {
                        "event_id": str(uuid.uuid4()), "event_type": "telemetry.metric.ingested",
                        "correlation_id": str(uuid.uuid4()),
                        "payload": {"workspace_id": str(workspace), "network_id": str(network),
                                    "device_id": value["device_id"], "metric": "cpu_usage", "value": 42.5,
                                    "unit": "percent", "observed_at": datetime.now(UTC).isoformat(),
                                    "source": "deployment_acceptance",
                                    "tags": {"synthetic": True, "quality": "test_fixture", "purpose": "archive_acceptance"}},
                    }
                    assert await TelemetryPersistenceService(db).persist_event(event)
                    row = await TelemetryRecordRepository(db).get_by_event_id(uuid.UUID(event["event_id"]))
                    await db.refresh(row)
                    if name == "pinned":
                        owner = TelemetryEvidenceService(db, scope=EvidenceOwnerScope(owner="report", workspace_id=workspace))
                        reference = EvidenceReference(network_id=network, reference_id=uuid.uuid4(), record_id=row.record_id)
                        await owner.pin(reference)
                        assert await owner.release(reference)  # Ever-pinned remains retained.
                    body = canonical_record(row)
                    result[name] = {"record_id": str(row.record_id), "event_id": str(row.event_id),
                                    "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}
                await db.commit()
                return result
            if action == "verify":
                expected = value["records"]
                for name in ("historical", "pinned"):
                    row = await db.get(TelemetryRecord, uuid.UUID(expected[name]["record_id"]))
                    assert row is not None
                    assert hashlib.sha256(canonical_record(row)).hexdigest() == expected[name]["sha256"]
                archived = expected["archive"]
                record_id = uuid.UUID(archived["record_id"])
                receipt = await TelemetryArchiveRepository(db).receipt(workspace, record_id)
                assert receipt is not None and receipt.sha256 == archived["sha256"]
                body = TelemetryArchiveStore("/var/lib/nanfo/telemetry-archive").read(receipt.sha256, receipt.size_bytes)
                assert len(body) == archived["bytes"]
                row = await db.get(TelemetryRecord, record_id)
                if value.get("restored"):
                    assert row is not None and canonical_record(row) == body
                else:
                    assert row is None
                assert not await TelemetryPersistenceService(db).persist_event({"event_id": archived["event_id"], "payload": {}})
                await db.commit()
                return {"archive_sha256": receipt.sha256, "archive_bytes": len(body),
                        "historical_retained": True, "released_pin_retained": True,
                        "tombstone_replay_rejected": True, "row_restored": bool(value.get("restored")),
                        "provenance": "synthetic_deployment_fixture_not_measured"}
            raise ValueError("Unknown fixture operation")
    finally:
        await get_engine().dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["historical", "prospective", "verify"])
    args = parser.parse_args()
    try:
        value = json.loads(sys.stdin.read(16385))
        print(json.dumps(asyncio.run(execute(args.action, value)), sort_keys=True))
    except Exception:  # noqa: BLE001 - private driver errors never enter exported evidence
        print(json.dumps({"status": "failed", "reason": "archive_acceptance_invariant"}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

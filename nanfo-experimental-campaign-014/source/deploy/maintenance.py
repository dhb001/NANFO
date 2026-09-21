"""Internal operator CLI for stopped-writer maintenance; not an application API.

Only backup_restore.py should invoke mutating restore-verify after verifying both
source and target owners are stopped. Read-only domain checkpoints belong to their
modules. Operator SQL below is confined to schema/aggregate diagnostic inspection.
"""

import argparse
import asyncio
import json
import sys


async def execute(action):
    import redis.asyncio as aioredis
    from app.core.config import get_settings
    from app.core.runtime_health import SCHEMA_HEAD, dependency_checks
    from app.db.postgres import AsyncSessionLocal, get_engine
    from app.events.realtime import API_REALTIME_LEASE_KEY
    from app.modules.autonomy.operations import (
        maintenance_checkpoint as autonomy_checkpoint,
    )
    from app.modules.autonomy.operations import model_reference_inventory
    from app.modules.identity.operations import invalidate_restored_sessions
    from app.modules.intent.operations import (
        maintenance_checkpoint as intent_checkpoint,
    )
    from app.modules.network.operations import (
        maintenance_checkpoint as graph_checkpoint,
    )
    from app.modules.report.operations import ReportOperationsService
    from neo4j import AsyncGraphDatabase
    from sqlalchemy import text

    from deploy.adr023_checkpoint import (
        autonomous_execution_checkpoint,
        experimental_lab_checkpoint,
        telemetry_archive_checkpoint,
    )
    from deploy.asset_checkpoint import asset_checkpoint

    settings = get_settings()
    redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    neo4j = AsyncGraphDatabase.driver(
        settings.NEO4J_URI, auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)
    )
    try:
        async with asyncio.timeout(120):
            dependencies = await dependency_checks(
                sessions=AsyncSessionLocal, redis=lambda: redis, neo4j=lambda: neo4j
            )
            if any(value != "ok" for value in dependencies.values()):
                return {"safe": False, "dependencies": dependencies}
            async with AsyncSessionLocal() as db:
                await db.execute(
                    text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                )
                await db.execute(text("SET LOCAL statement_timeout = '30s'"))
                intent = await intent_checkpoint(db)
                autonomy = await autonomy_checkpoint(db)
                autonomous_execution = await autonomous_execution_checkpoint(db)
                experimental_lab = await experimental_lab_checkpoint(db)
                reports = await ReportOperationsService(db).inventory(
                    verify=action != "diagnose"
                )
                reports.pop("registered_files")
                result = {
                    "safe": intent["safe"] and autonomy["safe"] and autonomous_execution["safe"] and experimental_lab["safe"],
                    "dependencies": dependencies,
                    "intent": intent,
                    "autonomy": autonomy,
                    "reports": reports,
                    "schema": SCHEMA_HEAD,
                    "model_references": await model_reference_inventory(db),
                    "neo4j_graph": await graph_checkpoint(neo4j),
                    "network_assets": await asset_checkpoint(db),
                    "telemetry_archive": await telemetry_archive_checkpoint(db),
                    "autonomous_execution": autonomous_execution,
                    "experimental_lab": experimental_lab,
                    "maintenance": "application admissions stopped by operator",
                }
                if action == "diagnose":
                    outbox = {}
                    # Fixed operator diagnostics only, never application business queries.
                    for table in (
                        "intent_outbox",
                        "report_outbox",
                        "alert_outbox",
                        "network_outbox",
                    ):
                        outbox[table] = await db.scalar(
                            text(
                                f"SELECT count(*) FROM {table} WHERE published_at IS NULL"
                            )
                        )
                    result["outbox_unpublished"] = outbox
                    result["queues"] = await queue_diagnostics(redis)
                    result["storage"] = {
                        "postgres_bytes": await db.scalar(
                            text("SELECT pg_database_size(current_database())")
                        ),
                        "telemetry_deletion": "explicit_bounded_operator_only; unknown_history_and_ever_pinned_retained",
                    }
            if action == "restore-verify" and result["safe"]:
                result["invalidated_sessions"] = await invalidate_restored_sessions(
                    redis
                )
                # Every old owner is stopped, and only the API realtime lease is reset.
                result["api_lease_removed"] = await redis.delete(API_REALTIME_LEASE_KEY)
                result["durable_jobs"] = (
                    "preserved; reconcile before enabling physical lab control"
                )
            return result
    finally:
        await redis.aclose()
        await neo4j.close()
        await get_engine().dispose()


async def queue_diagnostics(redis):
    """Bound inspection, omit payloads/consumer identities and never trim streams."""
    queues, cursor, scans = [], 0, 0
    while True:
        cursor, keys = await redis.scan(
            cursor=cursor, match="*", _type="stream", count=100
        )
        scans += 1
        for key in keys:
            if len(queues) >= 100:
                return {"streams": queues, "truncated": True}
            info = await redis.xinfo_stream(key)
            groups = await redis.xinfo_groups(key)
            pending, oldest_idle = 0, 0
            for group in groups[:100]:
                pending += group["pending"]
                if group["pending"]:
                    samples = await redis.xpending_range(
                        key, group["name"], "-", "+", 1
                    )
                    if samples:
                        oldest_idle = max(
                            oldest_idle, samples[0]["time_since_delivered"]
                        )
            queues.append(
                {
                    "stream_index": len(queues),
                    "length": info["length"],
                    "groups": len(groups),
                    "pending": pending,
                    "sample_oldest_idle_ms": oldest_idle,
                    "groups_truncated": len(groups) > 100,
                }
            )
        if cursor == 0 or scans >= 1000:
            return {"streams": queues, "truncated": cursor != 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=["quiesce", "checkpoint", "restore-verify", "diagnose"]
    )
    args = parser.parse_args()
    try:
        result = asyncio.run(execute(args.action))
        print(json.dumps(result, sort_keys=True))
        return 0 if result.get("safe") or args.action == "diagnose" else 1
    except Exception:  # noqa: BLE001 - never expose driver credentials or domain payloads
        print(
            json.dumps(
                {
                    "safe": False,
                    "reason": "Maintenance dependencies/checkpoint unavailable",
                }
            )
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())

"""Network-owned read-only cold-backup graph inventory; callers stop all writers."""

import asyncio
import hashlib
import json

from neo4j import READ_ACCESS


async def maintenance_checkpoint(driver, *, max_groups=1000, max_revisions=1_000_000):
    async def inspect(tx):
        result = {}
        for name, query in (
            ("nodes", "MATCH (n) RETURN count(n) AS count"),
            ("relationships", "MATCH ()-[r]->() RETURN count(r) AS count"),
            (
                "revision_tombstones",
                "MATCH (r:DeviceEventRevision) WHERE r.deleted = true RETURN count(r) AS count",
            ),
        ):
            row = await (await tx.run(query)).single(strict=True)
            if type(row["count"]) is not int or row["count"] < 0:
                raise ValueError("Invalid graph count")
            result[name] = row["count"]
        for name, query in (
            (
                "node_labels",
                "MATCH (n) UNWIND labels(n) AS identity RETURN identity, count(*) AS count ORDER BY identity LIMIT $limit",
            ),
            (
                "relationship_types",
                "MATCH ()-[r]->() RETURN type(r) AS identity, count(*) AS count ORDER BY identity LIMIT $limit",
            ),
        ):
            rows = await (await tx.run(query, limit=max_groups + 1)).data()
            if len(rows) > max_groups or any(
                len(row["identity"]) > 256 for row in rows
            ):
                raise ValueError("Graph inventory group cap exceeded")
            result[name] = rows
        revisions = await tx.run(
            """
            MATCH (r:DeviceEventRevision)
            RETURN r.device_id AS device_id, r.epoch_us AS epoch_us,
                   r.rank AS rank, r.event_id AS event_id, r.deleted AS deleted,
                   r.sequence AS sequence
            ORDER BY device_id, epoch_us, rank, event_id, deleted LIMIT $limit
        """,
            limit=max_revisions + 1,
        )
        digest, count = hashlib.sha256(), 0
        async for row in revisions:
            count += 1
            if count > max_revisions:
                raise ValueError("Graph revision inventory cap exceeded")
            record = dict(row)
            # C13 outbox sequences are covered when present; revisions written before
            # sequences existed hash exactly as before, so older backups still verify.
            if record.get("sequence") is None:
                record.pop("sequence", None)
            raw = json.dumps(
                record, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode()
            if len(raw) > 4096:
                raise ValueError("Graph revision record cap exceeded")
            digest.update(raw + b"\n")
        result.update(revisions=count, revisions_sha256=digest.hexdigest())
        return result

    async with (
        asyncio.timeout(60),
        driver.session(default_access_mode=READ_ACCESS) as session,
        await session.begin_transaction(timeout=55) as tx,
    ):
        return await inspect(tx)
